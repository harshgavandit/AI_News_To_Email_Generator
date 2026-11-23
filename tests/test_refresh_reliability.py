from concurrent.futures import ThreadPoolExecutor
import json
from dataclasses import replace
from pathlib import Path
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient

from app import discovery, discovery_health, ingestion, launch_store, news, server
from app.sources import BY_ID

SWEEP = "/api/jobs/refresh?run=scheduled"
JOB_HEADERS = {"Authorization": "Bearer scoped-refresh-for-tests"}
OWNER_HEADERS = {"Authorization": "Bearer owner-key-for-tests-0123456789abcdef0123"}
VERCEL_HEADERS = {"Authorization": "Bearer cron-secret-for-tests"}
VERCEL_SWEEP = "/api/jobs/feed-sweep"
MORNING = datetime(2026, 11, 17, 2, 30, tzinfo=UTC)
EVENING = MORNING + timedelta(hours=12)


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
    monkeypatch.setattr(discovery_health, "get_store", lambda: store)
    monkeypatch.setenv("FEED_REFRESH_SECRET", "scoped-refresh-for-tests")
    monkeypatch.setenv("CRON_SECRET", "cron-secret-for-tests")
    monkeypatch.setenv("ADMIN_TOKEN", "owner-key-for-tests-0123456789abcdef0123")
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
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["status"] == "already_started"
    assert client.post("/api/admin/refresh", headers={"Authorization": "Bearer owner-key-for-tests-0123456789abcdef0123"}).status_code == 429

    monkeypatch.setattr(launch_store.time, "time", lambda: lease + 1)
    new_lease = second_worker.claim_refresh()
    assert new_lease > lease
    store.finish_refresh(lease)
    assert store.claim_refresh() is None


def test_failed_check_is_logged_and_keeps_snapshot_until_evening(archive, monkeypatch, daily_clock, caplog):
    store, client = archive
    daily_clock(datetime(2026, 11, 16, 3, tzinfo=UTC))
    store.ingest("bbc-tech", [], True)
    previous = store.source_state()["bbc-tech"]["last_success"]
    daily_clock(datetime(2026, 11, 17, 3, tzinfo=UTC))
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", tuple(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech"))
    # The sweep retries a transient failure once; both attempts fail here.
    outcomes = iter([(False, "fetch_failed"), (False, "fetch_failed"), (True, None)])

    def fetch(_, **kwargs):
        available, error = next(outcomes)
        return [], {"available": available, "error": error}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    result = client.get(SWEEP, headers=JOB_HEADERS).json()
    assert (result["checked"], result["healthy"], result["remaining"]) == (1, 0, 0)
    assert result["failures"] == [{"id": "bbc-tech", "label": BY_ID["bbc-tech"].label, "reason": "fetch_failed"}]
    assert "publisher_check_failed source_id=bbc-tech" in caplog.text
    assert store.source_state()["bbc-tech"]["last_success"] == previous
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["status"] == "complete"
    response = client.post("/api/admin/refresh?source=bbc-tech", headers=OWNER_HEADERS)
    assert response.json()["sources"][0]["available"] is False
    daily_clock(EVENING)
    response = client.post("/api/admin/refresh?source=bbc-tech", headers=OWNER_HEADERS)
    assert response.json()["sources"][0]["available"] is True
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["checked"] == 0


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
        assert store.current_feed_validators()[source.id]["expires"] > datetime.now(UTC).timestamp() + 12 * 3600
    ingestion.refresh_sources(store, only=source.id)
    assert requests == [(source.url, None), (target, None), (source.url, None), (target, 'W/"rss-v1"'),
                        (source.url, None), (target, 'W/"rss-v1"'), (source.url, None), (target, None)]
    assert store.source_state()[source.id]["available"] is True


def test_region_reload_reads_archive_and_only_owner_can_refresh_a_source(archive, monkeypatch, daily_clock):
    store, client = archive
    ids = {"tech-in-asia", "sifted", "bbc-tech"}
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", tuple(s for s in ingestion.DEFAULT_SOURCES if s.id in ids))
    daily_clock(MORNING - timedelta(hours=12))
    store.ingest("bbc-tech", [], True)
    store.ingest("sifted", [], False, "fetch_failed")
    store.ingest("tech-in-asia", [], False, "fetch_failed")
    daily_clock(MORNING)
    refreshed = []

    def fetch(source, **kwargs):
        refreshed.append(source.id)
        return [], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    previous = client.get("/api/news?region=EU&force=true").json()
    assert previous["freshness"]["counts"] == {"enabled": 1, "fresh": 0, "stale": 0, "failed": 1, "pending": 0}
    assert not refreshed
    assert client.post("/api/admin/refresh?source=sifted").status_code == 401
    owner = {"Authorization": "Bearer owner-key-for-tests-0123456789abcdef0123"}
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


def test_twelve_hour_archive_updates_after_an_owner_refresh(archive, monkeypatch, daily_clock):
    store, client = archive
    now = MORNING
    monkeypatch.setattr(discovery, "datetime", ingestion.datetime)
    monkeypatch.setattr(launch_store, "datetime", ingestion.datetime)
    source = next(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech")
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    daily_clock(now - timedelta(minutes=16))

    def story(ident, age):
        return {"id": ident, "title": f"Story {ident}", "description": "Story details.",
                "url": f"https://www.bbc.com/news/{ident}", "source": source.group, "publisher": source.label,
                "published_at": (now - age).isoformat(), "category": "News"}

    recent = story("recent", timedelta(hours=11, minutes=59))
    older = story("older", timedelta(hours=12, minutes=1))
    store.ingest(source.id, [older, recent], True)
    daily_clock(now)
    newest = story("newest", timedelta(minutes=5))
    fetched = []

    def fetch(feed, **kwargs):
        fetched.append(feed.id)
        return [newest, recent], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    initial = client.get("/api/news?hours=12").json()
    assert [row["id"] for row in initial["articles"]] == ["recent"]
    assert not fetched
    owner = {"Authorization": "Bearer owner-key-for-tests-0123456789abcdef0123"}
    assert client.post("/api/admin/refresh?source=bbc-tech", headers=owner).status_code == 200
    updated = client.get("/api/news?hours=12&force=true").json()
    assert [row["id"] for row in updated["articles"]] == ["newest", "recent"]
    assert client.get("/api/news?hours=24").json()["total"] == 3
    assert fetched == [source.id]
    preview = client.post("/api/digest", json={"edition": "world", "hours": 12}).json()
    assert {row["digest_id"] for row in preview["digest"]["articles"]} == {"newest", "recent"}


def test_sweeps_check_the_full_catalog_once_each_and_respect_boundaries(archive, monkeypatch, daily_clock):
    _, client = archive
    sources = {source.id for source in ingestion.DEFAULT_SOURCES if source.enabled}
    attempts = []

    def fetch(source, **kwargs):
        attempts.append(source.id)
        return [], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    monkeypatch.setenv("FEED_REFRESH_MODE", "adaptive")
    for scheduled in (MORNING, EVENING):
        attempts.clear()
        daily_clock(scheduled - timedelta(seconds=1))
        assert client.get(SWEEP, headers=JOB_HEADERS).json() == {"status": "closed", "scheduled_at": scheduled.isoformat()}
        assert client.post("/api/admin/refresh?source=bbc-tech", headers=OWNER_HEADERS).json()["status"] == "closed"
        daily_clock(scheduled)
        headers = {**VERCEL_HEADERS, "ce-vssscheduledat": scheduled.isoformat()}
        assert client.post(VERCEL_SWEEP, headers={**headers, **JOB_HEADERS}).status_code == 401
        late = {**headers, "ce-vssscheduledat": (scheduled - timedelta(hours=12)).isoformat()}
        assert client.post(VERCEL_SWEEP, headers=late).status_code == 503
        for path in ("/api/jobs/refresh", "/api/jobs/refresh?fallback=02"):
            assert client.get(path, headers=JOB_HEADERS).json() == {"status": "inactive"}
        assert not attempts
        response = client.post(VERCEL_SWEEP, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["remaining"] == 0
        assert not result["unconfirmed"]
        assert result["checked"] == len(sources)
        assert client.post(VERCEL_SWEEP, headers=headers).json()["status"] == "complete"
        assert client.get(SWEEP, headers=JOB_HEADERS).json()["status"] == "complete"
        assert len(attempts) == len(sources) and set(attempts) == sources
        daily_clock(scheduled + timedelta(minutes=45))
        # Vercel's delivery is refused after its window; the follow-up may still finish the sweep.
        assert client.post(VERCEL_SWEEP, headers=headers).status_code == 503
        assert client.get(SWEEP, headers=JOB_HEADERS).json()["status"] == "complete"
        assert len(attempts) == len(sources)
        assert client.get("/api/ready").json()["freshness"]["counts"]["fresh"] == len(sources)
        assert client.get("/api/discovery/ingestion").json()["status"] == "running"


def test_publisher_followup_drains_only_inside_the_two_daily_sweep_windows():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "vercel.json").read_text(encoding="utf-8"))
    assert config["schedules"] == {"publisher-feed-sweep": {
        "schedule": "0 8,20 * * *", "timezone": "Asia/Kolkata",
        "path": VERCEL_SWEEP, "requestMethod": "POST",
    }}
    assert all(item["path"].startswith("/api/jobs/intelligence") for item in config["crons"])
    workflow = (root / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    refresh_job = workflow.split("  refresh:\n", 1)[1].split("  mail:\n", 1)[0]
    assert "github.event_name == 'workflow_dispatch'" in refresh_job
    assert "- cron: '40 2,14 * * *'" in workflow
    assert "github.event.schedule == '40 2,14 * * *'" in refresh_job
    assert "github.event.schedule == '2-57/5 * * * *'" not in refresh_job
    assert "--retry" not in refresh_job


def test_publisher_backoff_skips_evening_and_recovers_the_next_morning(archive, monkeypatch, daily_clock):
    store, client = archive
    source = BY_ID["bbc-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    daily_clock(MORNING)
    replies = iter([(False, "rate_limited", 13 * 3600), (True, None, 0)])
    calls = []

    def fetch(feed, **kwargs):
        calls.append(feed.id)
        available, error, retry = next(replies)
        return [], {"available": available, "error": error, "retry_after": retry}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["healthy"] == 0
    daily_clock(EVENING)
    result = client.get(SWEEP, headers=JOB_HEADERS).json()
    assert result["checked"] == 0 and result["deferred"] == 1
    assert result["deferrals"][0]["retry_at"] == (MORNING + timedelta(hours=13)).isoformat()
    assert len(calls) == 1
    daily_clock(MORNING + timedelta(days=1))
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["healthy"] == 1
    assert len(calls) == 2


def test_interrupted_claim_survives_restart_and_recovers_in_the_next_sweep(archive, monkeypatch, daily_clock):
    store, client = archive
    source = BY_ID["bbc-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    morning = MORNING.isoformat(timespec="minutes")
    daily_clock(MORNING)
    assert store.claim_feed_check(source.id, morning)
    restarted = launch_store.Store(str(store.engine.url))
    monkeypatch.setattr(server, "get_store", lambda: restarted)
    assert not restarted.claim_feed_check(source.id, morning)
    fetched = []
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: (fetched.append(feed.id) or [], {"available": True}))
    result = client.get(SWEEP, headers=JOB_HEADERS).json()
    assert result["checked"] == 0 and result["unconfirmed"] == [source.id]
    assert not fetched
    daily_clock(EVENING)
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["healthy"] == 1
    assert fetched == [source.id]


def test_explicit_host_rate_limit_stops_queued_feeds_and_survives_a_new_runner(archive, monkeypatch, daily_clock):
    store, client = archive
    same_host = tuple(source for source in ingestion.DEFAULT_SOURCES if source.enabled and
                      ingestion.feed_host(source) == "github.com")[:5]
    other = BY_ID["bbc-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (*same_host, other))
    fetched = []

    def read(source, **kwargs):
        fetched.append(source.id)
        if source == other:
            return [], {"available": True}
        request = httpx.Request("GET", source.url)
        response = httpx.Response(429, headers={"Retry-After": "46800"}, request=request)
        error = httpx.HTTPStatusError("Rate limited", request=request, response=response)
        return [], {"available": False, **news.http_failure(error)}

    monkeypatch.setattr(ingestion, "read_feed", read)
    daily_clock(MORNING)
    first = client.get(SWEEP, headers=JOB_HEADERS).json()
    assert first["checked"] == 3 and first["deferred"] == 3 and first["healthy"] == 1
    assert len(fetched) == 3 and other.id in fetched
    restarted = launch_store.Store(str(store.engine.url))
    monkeypatch.setattr(server, "get_store", lambda: restarted)
    daily_clock(EVENING)
    evening = client.get(SWEEP, headers=JOB_HEADERS).json()
    assert evening["checked"] == 1 and evening["deferred"] == len(same_host)
    assert fetched[-1] == other.id


def test_follow_up_cron_runs_inside_both_ist_sweep_windows():
    from datetime import datetime, timedelta, timezone
    from app.ingestion import SWEEP_WINDOW, latest_sweep
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    minute, hours = workflow.split("- cron: '", 2)[2].split("'", 1)[0].split()[:2]
    for hour in map(int, hours.split(",")):
        fired = datetime(2026, 11, 21, hour, int(minute), tzinfo=timezone.utc)
        opened = latest_sweep(fired)
        # The follow-up must start after Vercel's sweep opens and leave time before the window closes.
        assert timedelta(minutes=5) <= fired - opened <= SWEEP_WINDOW - timedelta(minutes=20)


def test_follow_up_waits_for_a_running_vercel_batch():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    refresh_job = workflow.split("  refresh:\n", 1)[1].split("  mail:\n", 1)[0]
    assert '"$status" == "already_started"' in refresh_job and "sleep 30" in refresh_job


def test_transient_failures_are_retried_once_within_the_sweep(archive, monkeypatch, daily_clock):
    store, client = archive
    flaky, gone, steady = BY_ID["bbc-tech"], BY_ID["naver-d2"], BY_ID["the-verge"]
    gone = replace(gone, enabled=True)
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (flaky, gone, steady))
    fetched = []

    def read(source, **kwargs):
        fetched.append(source.id)
        if source.id == flaky.id and fetched.count(flaky.id) == 1:
            return [], {"available": False, "error": "fetch_timeout"}
        if source.id == gone.id:
            return [], {"available": False, "error": "feed_not_found"}
        return [], {"available": True}

    monkeypatch.setattr(ingestion, "read_feed", read)
    daily_clock(MORNING)
    result = client.get(SWEEP, headers=JOB_HEADERS).json()
    assert fetched.count(flaky.id) == 2  # The timeout is retried after the rest of the queue.
    assert fetched.count(gone.id) == 1   # A missing feed is not retried within the sweep.
    assert fetched.count(steady.id) == 1
    state = store.source_state(include_archive=False)
    assert state[flaky.id]["available"] is True and state[gone.id]["available"] is False
    assert result["remaining"] == 0 and not result.get("unconfirmed")


def test_late_follow_up_finishes_the_same_sweep_once_and_closes_before_the_next(archive, monkeypatch, daily_clock):
    """GitHub can start the follow-up hours late; it still completes the sweep Vercel began."""
    store, client = archive
    sources = tuple(source for source in ingestion.DEFAULT_SOURCES if source.enabled)[:6]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", sources)
    fetched = []
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: (fetched.append(feed.id) or [], {"available": True}))
    # Vercel's batch reached only the first two sources before its window ended.
    daily_clock(MORNING + timedelta(minutes=5))
    ingestion.refresh_sources(store, source_ids={source.id for source in sources[:2]}, scheduled=MORNING)
    assert len(fetched) == 2
    daily_clock(MORNING + timedelta(hours=7, minutes=47))  # The follow-up ran 7 hours late.
    result = client.get(SWEEP, headers=JOB_HEADERS).json()
    assert result["status"] == "refreshed" and result["checked"] == 4 and result["remaining"] == 0
    assert sorted(fetched) == sorted(source.id for source in sources)
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["status"] == "complete"
    assert len(fetched) == 6, "each source is checked once per sweep"
    assert client.get("/api/ready").json()["freshness"]["counts"]["fresh"] == 6
    daily_clock(MORNING + ingestion.SWEEP_CATCHUP)
    assert client.get(SWEEP, headers=JOB_HEADERS).json() == {"status": "closed", "scheduled_at": EVENING.isoformat()}
    assert ingestion.SWEEP_CATCHUP <= ingestion.SWEEP_INTERVAL - timedelta(hours=1)


def test_second_follow_up_cron_covers_skipped_github_runs():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    refresh_job = workflow.split("  refresh:\n", 1)[1].split("  mail:\n", 1)[0]
    assert "- cron: '17 5,17 * * *'" in workflow
    assert "github.event.schedule == '17 5,17 * * *'" in refresh_job
    from app.ingestion import SWEEP_CATCHUP, latest_sweep
    for hour in (5, 17):
        fired = datetime(2026, 11, 21, hour, 17, tzinfo=UTC)
        assert fired - latest_sweep(fired) < SWEEP_CATCHUP - timedelta(hours=1)


def test_unfinished_sweep_hands_off_to_a_continuation_run(archive, monkeypatch, daily_clock):
    """Vercel's run checks what fits its budget, then a continuation run finishes the same sweep."""
    store, client = archive
    sources = tuple(source for source in ingestion.DEFAULT_SOURCES if source.enabled)[:5]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", sources)
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("CRON_SECRET", "cron-secret-for-tests-0123")
    fetched, handoffs = [], []
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: (fetched.append(feed.id) or [], {"available": True}))
    real_refresh = ingestion.refresh_sources

    def budgeted(store_, only=None, *, source_ids=None, **kwargs):
        # The scheduled run's budget runs out after two feeds.
        if kwargs.get("deadline") is not None and not handoffs:
            source_ids = set(sorted(source_ids)[:2])
        return real_refresh(store_, only, source_ids=source_ids, **kwargs)

    monkeypatch.setattr(server, "refresh_sources", budgeted)

    def handoff(url, *, params, headers, **kwargs):
        handoffs.append((url, params, headers["Authorization"]))
        raise httpx.ReadTimeout("the continuation keeps running")

    monkeypatch.setattr(server.httpx, "get", handoff)
    daily_clock(MORNING + timedelta(minutes=2))
    headers = {"Authorization": "Bearer cron-secret-for-tests-0123", "ce-vssscheduledat": MORNING.isoformat()}
    response = client.post(VERCEL_SWEEP, headers=headers)
    result = response.json()
    assert response.status_code == 503 and result["remaining"] == 3 and result["handed_off"] is True
    assert handoffs == [("https://getinformdaily.com/api/jobs/refresh", {"run": "continue", "hop": 1},
                         "Bearer cron-secret-for-tests-0123")]
    # The continuation (accepted with the same secret) finishes the sweep and stops chaining.
    daily_clock(MORNING + timedelta(minutes=7))
    result = client.get("/api/jobs/refresh?run=continue&hop=1", headers={"Authorization": handoffs[0][2]}).json()
    assert result["status"] == "refreshed" and result["checked"] == 3 and result["remaining"] == 0
    assert result["handed_off"] is False and len(handoffs) == 1
    assert sorted(fetched) == sorted(source.id for source in sources), "each feed is checked once per sweep"
    assert client.get("/api/ready").json()["freshness"]["counts"]["fresh"] == 5
    # A finished sweep, a run outside production and the hop limit never hand off.
    assert client.get("/api/jobs/refresh?run=continue&hop=2", headers=JOB_HEADERS).json()["status"] == "complete"
    assert client.get("/api/jobs/refresh?run=continue&hop=99", headers=JOB_HEADERS).status_code == 422
    assert server.continue_sweep({"status": "refreshed", "remaining": 4}, server.SWEEP_CHAIN_LIMIT) is False
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert server.continue_sweep({"status": "refreshed", "remaining": 4}, 0) is False
    assert len(handoffs) == 1


def test_continuation_runs_respect_the_sweep_window(archive, monkeypatch, daily_clock):
    _, client = archive
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: ([], {"available": True}))
    daily_clock(MORNING + ingestion.SWEEP_CATCHUP)
    assert client.get("/api/jobs/refresh?run=continue&hop=1", headers=JOB_HEADERS).json() == {
        "status": "closed", "scheduled_at": EVENING.isoformat(), "handed_off": False}
    assert client.get("/api/jobs/refresh?run=continue").status_code == 401
