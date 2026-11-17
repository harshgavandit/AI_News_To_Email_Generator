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
    store = launch_store.connect(f"sqlite:///{tmp_path / 'refresh.db'}")
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setenv("FEED_REFRESH_SECRET", "scoped-refresh-for-tests")
    monkeypatch.setenv("ADMIN_TOKEN", "owner-key-for-tests")
    return store, TestClient(server.app)


def test_manual_and_scheduled_runs_share_one_expiring_lease(archive, monkeypatch):
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


def test_failed_refresh_can_retry_and_preserves_successful_snapshot(archive, monkeypatch):
    store, client = archive
    store.ingest("bbc-tech", [], True)
    with store.engine.begin() as conn:
        conn.execute(launch_store.sources.update().where(launch_store.sources.c.id == "bbc-tech")
                     .values(checked=(datetime.now(UTC) - timedelta(minutes=20)).timestamp()))
    previous = store.source_state()["bbc-tech"]["last_success"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", tuple(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech"))
    outcomes = iter([(False, "fetch_failed"), (True, None)])

    def fetch(_, **kwargs):
        available, error = next(outcomes)
        return [], {"available": available, "error": error}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    headers = {"Authorization": "Bearer scoped-refresh-for-tests"}
    assert client.get("/api/jobs/refresh", headers=headers).status_code == 503
    assert store.source_state()["bbc-tech"]["last_success"] == previous
    response = client.get("/api/jobs/refresh", headers=headers)
    assert response.json() == {"status": "refreshed", "sources": 1, "healthy": 1, "checked": 1}
    assert client.get("/api/jobs/refresh", headers=headers).json()["status"] == "already_started"


def test_publisher_freshness_is_separate_from_overall_archive_health(archive, monkeypatch):
    store, client = archive
    now = datetime.now(UTC)
    monkeypatch.setattr(launch_store.time, "time", lambda: (now - timedelta(hours=2)).timestamp())
    store.ingest("bbc-tech", [], True)
    monkeypatch.setattr(launch_store.time, "time", now.timestamp)
    store.ingest("guardian-tech", [], True)
    bbc = client.get("/api/news", params={"publisher": "bbc-tech"}).json()["freshness"]
    assert bbc["status"] == "stale"
    assert bbc["last_success"] == (now - timedelta(hours=2)).isoformat()
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


def test_region_freshness_and_retry_target_matching_feeds(archive, monkeypatch):
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
    assert previous["refresh_requested"] is True
    result = client.get("/api/news?region=EU").json()
    assert result["freshness"]["status"] == "fresh"
    assert refreshed == ["sifted"]


def test_first_reader_can_start_an_empty_archive(archive, monkeypatch):
    _, client = archive
    source = next(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech")
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    monkeypatch.setattr(ingestion, "read_feed", lambda _, **kwargs: ([], {"available": True}))
    first = client.get("/api/news?hours=12")
    assert first.json()["freshness"]["status"] == "pending"
    assert "Vercel-CDN-Cache-Control" not in first.headers
    assert client.get("/api/news?hours=12").json()["freshness"]["status"] == "fresh"


def test_twelve_hour_view_excludes_older_stories_and_refreshes_stale_archive_once(archive, monkeypatch):
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
    updated = client.get("/api/news?hours=12").json()
    assert [row["id"] for row in updated["articles"]] == ["newest", "recent"]
    assert client.get("/api/news?hours=24").json()["total"] == 3
    assert fetched == [source.id]
    preview = client.post("/api/digest", json={"edition": "world", "hours": 12}).json()
    assert {row["digest_id"] for row in preview["digest"]["articles"]} == {"newest", "recent"}
