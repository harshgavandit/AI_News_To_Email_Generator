from datetime import UTC, datetime
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import event_intelligence, insight_api, monitoring, server, stack_intelligence
from app.launch_store import Store, monitor_alerts
from app.sources import BY_ID
from app.web_digest import digest_markdown, safe_email_html


@pytest.fixture
def reader_client(research_database, monkeypatch):
    store = Store(research_database)
    store.migrate()
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(insight_api, "get_store", lambda: store)
    with TestClient(server.app) as client:
        yield store, client
    store.engine.dispose()


def seed(store, source_id, title, excerpt):
    source = BY_ID[source_id]
    row = {"id": source_id, "source_id": source.id, "source": source.group, "publisher": source.label,
           "title": title, "description": excerpt, "kind": source.kind, "category": "Technology",
           "url": f"https://{source.hosts[0]}/reader-case", "published_at": datetime.now(UTC).isoformat()}
    store.ingest(source.id, [row], True)
    return event_intelligence.observe(store, row)[0]


def test_source_bound_impact_and_development_reads(reader_client):
    store, client = reader_client
    event_id = seed(store, "google-cloud-status", "Google Cloud incident update",
                   "Compute Engine was affected in us-central1 while Storage was affected in europe-west1.")
    payload = {"article_id": "google-cloud-status", "cloud": [
        {"provider": "google-cloud", "service": "Compute Engine", "region": region}
        for region in ("us-central1", "europe-west1")]}
    response = client.post("/api/intelligence/personal-impact", json=payload)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert [row["status"] for row in data["cloud"]] == ["match", "unknown"]
    assert data["cloud"][0]["evidence"][0]["excerpt"] == "Compute Engine was affected in us-central1"
    assert client.post("/api/intelligence/personal-impact", json=payload, headers={"Origin": "https://unrelated.test"}).status_code == 403

    timeline = client.get("/api/intelligence/events/" + event_id).json()
    assert timeline["latest_material"]["source"]["id"] == "google-cloud-status"
    assert timeline["coverage_freshness"]["feeds"][0]["id"] == "google-cloud-status"
    assert timeline["coverage_freshness"]["feeds"][0]["checked_at"]
    assert client.get(f"/development.html?id={event_id}").status_code == 200
    coverage = client.post("/api/intelligence/research", json={"q": "Compute Engine incident", "mode": "search",
        "scope": {"topic": "outages"}}).json()["coverage_freshness"]
    assert coverage["scope"] == "Selected topic and evidence feeds"
    assert coverage["counts"]["enabled"] > 0
    # Plain and HTML email link back to the exact development endpoint.
    digest = {"articles": [{"rank": 1, "title": "Google Cloud incident", "development_id": event_id}],
              "introduction": {"greeting": "Reader"}}
    assert f"/development.html?id={event_id}" in digest_markdown(digest)
    assert f"/development.html?id={event_id}" in safe_email_html(digest)


def test_exact_package_impact_requires_the_advisory_identity(reader_client, monkeypatch):
    store, client = reader_client
    seed(store, "ars-technica", "Publisher covers CVE-2024-12345", "The article discusses advisory CVE-2024-12345.")
    def lookup(_store, package):
        aliases = ["CVE-2024-12345"] if package.version == "1.0.0" else ["CVE-2024-54321"]
        return {"evidence": [{"id": "GHSA-abcd-efgh-ijkl", "aliases": aliases,
            "title": "Library advisory", "publisher": "OSV", "published_at": "",
            "url": "https://osv.dev/vulnerability/GHSA-abcd-efgh-ijkl"}]}
    monkeypatch.setattr(stack_intelligence, "advisories", lookup)
    request = {"article_id": "ars-technica", "packages": [
        {"ecosystem": "npm", "name": "test-library", "version": version} for version in ("1.0.0", "2.0.0")]}
    data = client.post("/api/intelligence/personal-impact", json=request).json()
    assert [row["status"] for row in data["packages"]] == ["match", "unknown"]
    assert data["packages"][0]["evidence"][0]["publisher"] == "OSV"


def test_inbox_actions_are_private_and_pause_scheduled_watches(reader_client):
    store, client = reader_client
    root = "/api/intelligence/inbox"
    watches = {"watches": [{"id": "cloud", "query": "regional cloud", "topic": "all"}]}
    assert client.post(root + "/enable", json=watches).status_code == 201
    other = TestClient(server.app)
    assert other.post(root + "/enable", json=watches).status_code == 201
    ident = hashlib.sha256(client.cookies.get(monitoring.COOKIE).encode()).hexdigest()
    alert = "a" * 32
    now = time.time()
    with store.engine.begin() as conn:
        conn.execute(monitor_alerts.insert().values(id=alert, watch_id="cloud", profile_id=ident,
            created=now, updated=now, evidence=json.dumps([])))
    assert other.post(root + "/read/" + alert).status_code == 404
    assert client.get(root).json()["unread"] == 1
    result = client.put(root + "/watches/cloud/delivery", json={"action": "snooze"}).json()
    assert result["watches"][0]["delivery"]["snoozed_until"] > now
    assert result["alerts"] == []
    assert other.put(root + "/watches/cloud/delivery", json={"action": "mute"}).status_code == 200
    assert monitoring.run_monitoring(store)["watches_checked"] == 0
    result = client.put(root + "/watches/cloud/delivery", json={"action": "resume"}).json()
    assert result["unread"] == 1
    assert client.post(root + "/read/" + alert).json()["unread"] == 0
    assert monitoring.run_monitoring(store)["watches_checked"] == 1
