from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient

from app import ingestion, launch_store, news, server
from app.sources import BY_ID


def test_direct_feed_rate_limits_preserve_previous_records(monkeypatch):
    source = BY_ID["bbc-tech"]
    monkeypatch.setattr(news, "DEFAULT_SOURCES", (source,))
    monkeypatch.setattr(news, "_cache", {})
    monkeypatch.setattr(news, "_refreshed", 0)
    clock = iter((1000, 1000, 1301, 1301, 1602, 1602))
    monkeypatch.setattr(news, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    item = {"id": "previous", "published_at": datetime.now(UTC).isoformat()}
    replies = iter([([item], {"available": True}),
                    ([], {"available": False, "error": "rate_limited", "retry_after": 900})])
    attempts = []

    def fetch(feed):
        attempts.append(feed.id)
        return next(replies)

    monkeypatch.setattr(news, "safe_read_feed", fetch)
    assert news.collect_news()["articles"] == [item]
    for _ in range(2):
        result = news.collect_news()
        assert result["articles"] == [item]
        assert result["sources"][0]["retry_at"] > result["sources"][0]["checked_at"]
    assert attempts == [source.id, source.id]


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("FEED_REFRESH_MODE", "daily")
    store = launch_store.connect(f"sqlite:///{tmp_path / 'refresh.db'}")
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setenv("FEED_REFRESH_SECRET", "scoped-refresh-for-tests")
    monkeypatch.setenv("ADMIN_TOKEN", "owner-key-for-tests")
    return store, TestClient(server.app)


@pytest.fixture
def daily_clock(monkeypatch):
    moment = datetime(2026, 11, 17, 3, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    def set_time(value):
        nonlocal moment
        moment = value

    monkeypatch.setattr(server, "datetime", Clock)
    monkeypatch.setattr(ingestion, "datetime", Clock)
    monkeypatch.setattr(launch_store.time, "time", lambda: moment.timestamp())
    return set_time


def test_manual_and_scheduled_runs_share_one_expiring_lease(archive, monkeypatch, daily_clock):
    store, client = archive
    second_worker = launch_store.Store(str(store.engine.url))
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait(timeout=5)
        return worker.claim_refresh()

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(claim, (store, second_worker)))
    lease, = (value for value in leases if value is not None)
    monkeypatch.setattr(server, "refresh_sources", lambda *_: pytest.fail("An active refresh already holds the lease"))
    assert client.get("/api/jobs/refresh", headers={"Authorization": "Bearer scoped-refresh-for-tests"}).json()["status"] == "already_started"
    assert client.post("/api/admin/refresh", headers={"Authorization": "Bearer owner-key-for-tests"}).status_code == 429

    monkeypatch.setattr(launch_store.time, "time", lambda: lease + 1)
    new_lease = second_worker.claim_refresh()
    assert new_lease > lease
    store.finish_refresh(lease)
    assert store.claim_refresh() is None


def test_failed_daily_check_preserves_snapshot_until_a_targeted_retry(archive, monkeypatch, daily_clock):
    store, client = archive
    daily_clock(datetime(2026, 11, 16, 3, tzinfo=UTC))
    store.ingest("bbc-tech", [], True)
    previous = store.source_state()["bbc-tech"]["last_success"]
    daily_clock(datetime(2026, 11, 17, 3, tzinfo=UTC))
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", tuple(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech"))
    outcomes = iter([(False, "fetch_failed"), (True, None)])

    def fetch(_, **kwargs):
        available, error = next(outcomes)
        return [], {"available": available, "error": error}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    headers = {"Authorization": "Bearer scoped-refresh-for-tests"}
    result = client.get("/api/jobs/refresh", headers=headers).json()
    assert (result["checked"], result["healthy"], result["remaining"]) == (1, 0, 0)
    assert store.source_state()["bbc-tech"]["last_success"] == previous
    assert client.get("/api/jobs/refresh", headers=headers).json()["status"] == "complete"
    owner = {"Authorization": "Bearer owner-key-for-tests"}
    response = client.post("/api/admin/refresh?source=bbc-tech", headers=owner)
    assert response.json()["sources"][0]["available"] is True


def test_publisher_freshness_is_separate_from_overall_archive_health(archive, daily_clock):
    store, client = archive
    now = datetime(2026, 11, 17, 8, tzinfo=UTC)
    daily_clock(now - timedelta(days=1))
    store.ingest("bbc-tech", [], True)
    daily_clock(now)
    store.ingest("guardian-tech", [], True)
    bbc = client.get("/api/news", params={"publisher": "bbc-tech"}).json()["freshness"]
    assert bbc["status"] == "stale"
    assert bbc["last_success"] == (now - timedelta(days=1)).isoformat()
    guardian = client.get("/api/news", params={"publisher": "guardian-tech"}).json()["freshness"]
    assert guardian["status"] == "fresh"
    assert guardian["counts"] == {"enabled": 1, "fresh": 1, "stale": 0, "failed": 0, "pending": 0}
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["freshness"]["status"] == "degraded"


def test_readiness_fails_when_no_feed_has_succeeded(archive):
    _, client = archive
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["freshness"]["status"] == "pending"
    assert client.get("/api/health").status_code == 200


def test_retry_after_is_persisted_and_scoped_to_the_failed_feed(archive, monkeypatch):
    store, client = archive
    bbc, guardian = BY_ID["bbc-tech"], BY_ID["guardian-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (bbc, guardian))
    store.ingest(bbc.id, [], True)
    calls = []

    def fetch(source, **kwargs):
        calls.append(source.id)
        if calls.count(bbc.id) == 1 and source == bbc:
            response = httpx.Response(429, headers={"Retry-After": "3600"}, request=httpx.Request("GET", source.url))
            error = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
            return [], {"available": False, **news.http_failure(error)}
        return [], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    first = {feed["id"]: feed for feed in ingestion.refresh_sources(store)}
    assert first[bbc.id]["last_success"] and first[bbc.id]["error"] == "rate_limited"
    assert datetime.fromisoformat(first[bbc.id]["retry_at"]) > datetime.now(UTC) + timedelta(minutes=55)
    second_worker = launch_store.Store(str(store.engine.url))
    ingestion.refresh_sources(second_worker)
    assert calls.count(bbc.id) == 1 and calls.count(guardian.id) == 2
    assert not client.get(f"/api/news?publisher={bbc.id}&force=true").json().get("refresh_requested")

    with store.engine.begin() as conn:
        conn.execute(launch_store.feed_retries.update().values(retry_at=0))
    final = {feed["id"]: feed for feed in ingestion.refresh_sources(second_worker)}
    assert final[bbc.id]["freshness"] == "fresh" and "retry_at" not in final[bbc.id]
    assert store.source_state()[bbc.id]["retry_at"] is None
    second_worker.engine.dispose()


def test_conditional_refresh_preserves_articles_through_not_modified_and_outage(archive, monkeypatch):
    store, _ = archive
    source = BY_ID["bbc-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    target = source.url.rsplit("/", 1)[0] + "/conditional-fixture.xml"
    feed = f"""<rss version="2.0"><channel><title>Technology</title><item>
        <title>A trusted software update</title><link>https://www.bbc.com/news/technology-12345</link>
        <pubDate>{date}</pubDate><description>Publisher excerpt.</description>
        </item></channel></rss>"""
    modes = iter([200, 304, 503, 200])
    requests = []

    def handle(request):
        tag = request.headers.get("If-None-Match")
        requests.append((str(request.url), tag))
        if str(request.url) == source.url:
            return httpx.Response(301, headers={"Location": target})
        status = next(modes)
        return httpx.Response(status, text=feed if status == 200 else "", headers={"ETag": 'W/"rss-v1"'})

    original = httpx.AsyncClient
    monkeypatch.setattr(news.httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)))
    for expected_available in (True, True, False):
        ingestion.refresh_sources(store)
        state = store.source_state()[source.id]
        assert state["available"] == expected_available and state["count"] == 1 and state["retained_count"] == 1
        assert store.current_feed_validators()[source.id]["resource_url"] == target
    ingestion.refresh_sources(store, only=source.id)
    assert requests == [(source.url, None), (target, None), (source.url, None), (target, 'W/"rss-v1"'),
                        (source.url, None), (target, 'W/"rss-v1"'), (source.url, None), (target, None)]
    assert store.source_state()[source.id]["available"] is True


def test_region_reload_reads_archive_and_only_owner_can_refresh_a_source(archive, monkeypatch):
    store, client = archive
    ids = {"tech-in-asia", "sifted", "bbc-tech"}
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", tuple(s for s in ingestion.DEFAULT_SOURCES if s.id in ids))
    store.ingest("bbc-tech", [], True)
    store.ingest("sifted", [], False, "fetch_failed")
    store.ingest("tech-in-asia", [], False, "fetch_failed")
    refreshed = []

    def fetch(source, **kwargs):
        refreshed.append(source.id)
        return [], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    previous = client.get("/api/news?region=EU&force=true").json()
    assert previous["freshness"]["counts"] == {"enabled": 1, "fresh": 0, "stale": 0, "failed": 1, "pending": 0}
    assert not refreshed
    assert client.post("/api/admin/refresh?source=sifted").status_code == 401
    owner = {"Authorization": "Bearer owner-key-for-tests"}
    assert client.post("/api/admin/refresh?source=sifted", headers=owner).status_code == 200
    result = client.get("/api/news?region=EU&force=true").json()
    assert result["freshness"]["status"] == "fresh"
    assert refreshed == ["sifted"]


def test_reader_cannot_start_a_publisher_fetch_even_on_an_empty_archive(archive, monkeypatch):
    _, client = archive
    source = next(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech")
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    monkeypatch.setattr(ingestion, "read_feed", lambda _, **kwargs: pytest.fail("Reader polled a publisher"))
    first = client.get("/api/news?hours=12")
    assert first.json()["freshness"]["status"] == "pending"
    assert "Vercel-CDN-Cache-Control" not in first.headers
    assert client.get("/api/news?hours=12&force=true").json()["freshness"]["status"] == "pending"
    monkeypatch.setattr(server, "get_store", lambda: None)
    monkeypatch.setattr(news, "safe_read_feed", lambda _: pytest.fail("Missing archive polled a publisher"))
    assert client.get("/api/news?hours=12&force=true").json()["articles"] == []


def test_twelve_hour_archive_updates_after_an_owner_refresh(archive, monkeypatch):
    store, client = archive
    now = datetime.now(UTC)
    source = next(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech")
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    monkeypatch.setattr(launch_store.time, "time", lambda: (now - timedelta(minutes=16)).timestamp())

    def story(ident, age):
        return {"id": ident, "title": f"Story {ident}", "description": "Story details.",
                "url": f"https://www.bbc.com/news/{ident}", "source": source.group, "publisher": source.label,
                "published_at": (now - age).isoformat(), "category": "News"}

    recent = story("recent", timedelta(hours=11, minutes=59))
    older = story("older", timedelta(hours=12, minutes=1))
    store.ingest(source.id, [older, recent], True)
    monkeypatch.setattr(launch_store.time, "time", now.timestamp)
    newest = story("newest", timedelta(minutes=5))
    fetched = []

    def fetch(feed, **kwargs):
        fetched.append(feed.id)
        return [newest, recent], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    initial = client.get("/api/news?hours=12").json()
    assert [row["id"] for row in initial["articles"]] == ["recent"]
    assert not fetched
    owner = {"Authorization": "Bearer owner-key-for-tests"}
    assert client.post("/api/admin/refresh?source=bbc-tech", headers=owner).status_code == 200
    updated = client.get("/api/news?hours=12&force=true").json()
    assert [row["id"] for row in updated["articles"]] == ["newest", "recent"]
    assert client.get("/api/news?hours=24").json()["total"] == 3
    assert fetched == [source.id]
    preview = client.post("/api/digest", json={"edition": "world", "hours": 12}).json()
    assert {row["digest_id"] for row in preview["digest"]["articles"]} == {"newest", "recent"}


def test_morning_sweep_drains_host_limited_batches_once_at_eight(archive, monkeypatch, daily_clock):
    _, client = archive
    github = tuple(source for source in ingestion.DEFAULT_SOURCES if source.group == "github-releases")[:8]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", github)
    assert len(github) == 8
    attempts = []

    def fetch(source, **kwargs):
        attempts.append(source.id)
        return [], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    headers = {"Authorization": "Bearer scoped-refresh-for-tests"}
    morning = datetime(2026, 11, 17, 2, 30, tzinfo=UTC)
    daily_clock(morning - timedelta(seconds=1))
    assert client.get("/api/jobs/refresh", headers=headers).json() == {"status": "waiting", "scheduled_at": morning.isoformat()}
    assert not attempts
    daily_clock(morning)
    first = client.get("/api/jobs/refresh", headers=headers).json()
    assert (first["checked"], first["remaining"]) == (6, 2)
    second = client.get("/api/jobs/refresh", headers=headers).json()
    assert (second["checked"], second["remaining"]) == (2, 0)
    assert client.get("/api/jobs/refresh", headers=headers).json()["status"] == "complete"
    assert len(attempts) == len(set(attempts)) == 8

    daily_clock(morning + timedelta(hours=23))
    assert client.get("/api/ready").json()["freshness"]["counts"]["fresh"] == 8
    daily_clock(morning + timedelta(days=1, minutes=46))
    assert client.get("/api/ready").json()["freshness"]["counts"]["stale"] == 8


def test_adaptive_refresh_runs_before_morning_and_drains_bounded_batches(archive, monkeypatch, daily_clock):
    store, client = archive
    monkeypatch.setenv("FEED_REFRESH_MODE", "adaptive")
    daily_clock(datetime(2026, 11, 17, 1, tzinfo=UTC))
    sources = ingestion.DEFAULT_SOURCES[:70]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", sources)
    attempts, cleanups = [], []
    monkeypatch.setattr(store, "prune", lambda: cleanups.append(True))

    def fetch(source, **kwargs):
        attempts.append(source.id)
        return [], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    headers = {"Authorization": "Bearer scoped-refresh-for-tests"}
    first = client.get("/api/jobs/refresh", headers=headers).json()
    assert first["mode"] == "adaptive" and first["checked"] <= 64 and first["remaining"] > 0
    for _ in range(4):
        result = client.get("/api/jobs/refresh", headers=headers).json()
        if result["remaining"] == 0:
            break
    assert result["remaining"] == 0
    assert len(attempts) == len(set(attempts)) == 70
    assert len(cleanups) == 1
    assert client.get("/api/jobs/refresh", headers=headers).json()["status"] == "complete"
    feeds = ingestion.source_catalog(store)
    assert all(feed["refresh_policy"] == "adaptive" for feed in feeds)
    assert {feed["refresh_minutes"] for feed in feeds} != {1440}
    assert all(feed["checked_at"] < feed["next_check_at"] for feed in feeds)


def test_adaptive_refresh_respects_per_source_cadence_and_retry_after(archive, monkeypatch, daily_clock):
    store, client = archive
    monkeypatch.delenv("FEED_REFRESH_MODE", raising=False)
    source = BY_ID["bbc-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    moment = datetime(2026, 11, 17, 1, tzinfo=UTC)
    daily_clock(moment)
    replies = iter([(True, None, 0), (False, "rate_limited", 3600), (True, None, 0)])
    calls = []

    def fetch(feed, **kwargs):
        calls.append(feed.id)
        available, error, retry = next(replies)
        return [], {"available": available, "error": error, "retry_after": retry}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    headers = {"Authorization": "Bearer scoped-refresh-for-tests"}
    assert client.get("/api/jobs/refresh", headers=headers).json()["healthy"] == 1
    daily_clock(moment + timedelta(minutes=source.poll_minutes - 1))
    assert client.get("/api/jobs/refresh", headers=headers).json()["status"] == "complete"
    daily_clock(moment + timedelta(minutes=source.poll_minutes))
    assert client.get("/api/jobs/refresh", headers=headers).json()["healthy"] == 0
    assert len(calls) == 2
    assert client.get("/api/jobs/refresh", headers=headers).json()["status"] == "complete"
    daily_clock(moment + timedelta(minutes=source.poll_minutes + 61))
    assert client.get("/api/jobs/refresh", headers=headers).json()["healthy"] == 1
    assert len(calls) == 3
