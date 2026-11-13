from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app import ingestion, launch_store, server


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
    previous = store.source_state()["bbc-tech"]["last_success"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", tuple(s for s in ingestion.DEFAULT_SOURCES if s.id == "bbc-tech"))
    outcomes = iter([(False, "fetch_failed"), (True, None)])

    def fetch(_):
        available, error = next(outcomes)
        return [], {"available": available, "error": error}

    monkeypatch.setattr(ingestion, "read_feed", fetch)
    headers = {"Authorization": "Bearer scoped-refresh-for-tests"}
    assert client.get("/api/jobs/refresh", headers=headers).status_code == 503
    assert store.source_state()["bbc-tech"]["last_success"] == previous
    response = client.get("/api/jobs/refresh", headers=headers)
    assert response.json() == {"status": "refreshed", "sources": 1, "healthy": 1}
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
