"""Coverage linking, reviewed background rules, and workspace access through the public API."""
from datetime import UTC, datetime
import json
import time

from fastapi.testclient import TestClient
import pytest

from app import event_intelligence, monitoring, research, watch_rules
from app.launch_store import get_store
from app.server import app
from app.sources import BY_ID


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'technology.sqlite'}")
    monkeypatch.delenv("VERCEL", raising=False)
    store = get_store()
    store.migrate()
    return store


def entry(store, ident, feed, path, title, excerpt):
    source = BY_ID[feed]
    row = {"id": ident, "source": source.group, "source_id": feed, "publisher": source.label,
           "kind": source.kind, "category": source.topic or "software", "url": f"https://{source.hosts[0]}{path}",
           "published_at": datetime.now(UTC).isoformat(), "title": title, "description": excerpt}
    store.ingest(feed, [row], True)
    event_intelligence.observe(store, row)
    return row


def release(store, ident, version, excerpt, title=None):
    return entry(store, ident, "kubernetes-releases", f"/kubernetes/kubernetes/releases/tag/v{version}",
                 title or f"Release v{version}", excerpt)


def answer_stub(payload, system, schema, **kwargs):
    row = next(row for row in json.loads(payload)["evidence"] if row["excerpt"])
    return json.dumps({"status": "answered", "limitations": "Limited to the retained publisher excerpt.", "claims": [
        {"text": row["excerpt"], "kind": "fact", "source_ids": [row["id"]], "quotes": [row["excerpt"]]}]})


def enabled(client):
    result = client.post("/api/intelligence/inbox/enable", json={"watches": []})
    assert result.status_code == 201, result.text
    return result.json()


def test_technology_page_grounding_and_radar_follow(archive, monkeypatch):
    release(archive, "release", "1.34.0", "The release removes the old networking API.")
    entry(archive, "report", "ars-technica", "/fixture/cloud", "Kubernetes networking changes roll out",
          "Kubernetes operators are adjusting how they configure networking.")
    entry(archive, "unrelated", "ars-technica", "/fixture/other", "A Rust compiler update lands", "A new Rust compiler was released.")
    monkeypatch.setattr(research, "ai_enabled", lambda: True)
    monkeypatch.setattr(research, "generate_response", answer_stub)
    with TestClient(app) as browser:
        response = browser.get("/api/intelligence/technologies/kubernetes", params={"hours": 168})
        assert response.status_code == 200, response.text
        rows = {row["id"]: row for row in response.json()["records"]}
        assert set(rows) == {"report", "release"}
        assert rows["release"]["record_kind"] == "release"
        assert rows["release"]["entity_match"] == "registered_source"
        edition = browser.post("/api/intelligence/technologies/kubernetes/ask", json={}).json()
        assert edition["answer"]["claims"][0]["quotes"]
        catchup = browser.post("/api/intelligence/catchup", json={"profile": {"followed_technologies": ["kubernetes"]}}).json()
        assert any("Technology you follow: Kubernetes" in row["reasons"] for row in catchup["events"])


def test_draft_needs_review_and_background_checks_exact_filters(archive, monkeypatch):
    monkeypatch.setattr(research, "ai_enabled", lambda: True)
    rule = {"technology": "kubernetes", "event": "breaking", "version": "1.34.0", "region": ""}
    monkeypatch.setattr(watch_rules, "generate_response", lambda *args, **kwargs: json.dumps({"rule": rule}))
    with TestClient(app) as browser:
        current = enabled(browser)
        draft = browser.post("/api/intelligence/watch-draft", json={"intent": "Kubernetes v1.34.0 breaking changes"})
        assert draft.json()["rule"] == rule
        assert not browser.get("/api/intelligence/inbox").json()["watches"]
        watch = {"id": "reviewed-rule", "query": "Kubernetes breaking changes", "rule": draft.json()["rule"]}
        stored = browser.put("/api/intelligence/inbox/watches", json={"revision": current["revision"], "watches": [watch]})
        assert stored.status_code == 200, stored.text
        assert stored.json()["watches"][0]["rule"] == rule
        release(archive, "right", "1.34.0", "Breaking change: the networking API has been removed.")
        release(archive, "wrong-version", "1.34.0-rc.1", "Breaking change: a different API has been removed.")
        release(archive, "no-breaking", "1.34.1", "There are no breaking changes from v1.34.0.")
        outcome = monitoring.run_monitoring(archive, now=time.time() + 1)
        assert outcome["alerts_created"] == 1
        alert = browser.get("/api/intelligence/inbox").json()["alerts"][0]
        assert [row["id"] for row in alert["sources"]] == ["right"]


def test_collaboration_brief_revisions_and_revocation(archive, monkeypatch):
    release(archive, "release", "1.34.0", "The publisher initially reported support for the networking API.")
    monkeypatch.setattr(research, "ai_enabled", lambda: True)
    monkeypatch.setattr(research, "generate_response", answer_stub)
    base = "/api/intelligence/inbox/projects"
    with TestClient(app) as owner, TestClient(app) as colleague, TestClient(app) as reader:
        enabled(owner)
        enabled(colleague)
        enabled(reader)
        project = owner.post(base, json={"question": "What networking changes should operators track?",
                                        "technology": "kubernetes", "keywords": "networking"})
        assert project.status_code == 201, project.text
        project_url = f"{base}/{project.json()['id']}"
        assert reader.get(project_url).status_code == 404
        assert owner.get(project_url + "/discover").json()["evidence"][0]["id"] == "release"
        token = owner.post(project_url + "/invite").json()["token"]
        assert colleague.post(base + "/join", json={"token": token}).status_code == 201
        assert reader.post(base + "/join", json={"token": token}).status_code == 404
        assert colleague.put(project_url + "/sources", json={"article_id": "release", "note": "Private team note"}).status_code == 200
        assert owner.put(project_url + "/sources", json={"article_id": "release"}).status_code == 200
        assert owner.get(project_url).json()["sources"][0]["note"] == "Private team note"
        edition = owner.post(project_url + "/brief", json={"audience": "security", "window": "week"})
        assert edition.status_code == 201, edition.text
        assert edition.json()["answer"]["status"] == "answered"
        body = {"token": edition.json()["id"]}
        opened = reader.post("/api/intelligence/briefs/open", json=body)
        assert opened.status_code == 200
        assert "Private team note" not in opened.text
        release(archive, "release", "1.34.0", "The previous record was corrected. Networking API support is still under review.",
                title="Correction: Networking API support remains under review")
        history = reader.get("/api/intelligence/source-history/release").json()
        assert history["editorial_notice"] == "correction"
        assert len(history["revisions"]) == 2
        assert history["revisions"][-1]["editorial_notice"] == "correction"
        updated = reader.post("/api/intelligence/briefs/open", json=body).json()
        assert updated["evidence_changed"] and not updated["answer"]["claims"]
        assert owner.delete(project_url + "/collaborators").status_code == 200
        assert colleague.get(project_url).status_code == 404
        assert owner.delete(project_url + "/briefs/" + body["token"]).status_code == 200
        assert reader.post("/api/intelligence/briefs/open", json=body).status_code == 404
        assert owner.delete("/api/intelligence/inbox").status_code == 200
        assert owner.get(base).status_code == 401
