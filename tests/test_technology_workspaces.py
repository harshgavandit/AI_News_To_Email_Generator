"""Coverage linking, reviewed background rules, and workspace access through the public API."""
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from xml.etree import ElementTree

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


def test_public_tracker_html_matches_sitemap_and_keeps_publisher_context(archive):
    article = release(archive, "landing", "1.34.0", "Publisher excerpt for the interactive reader.",
                      title="Kubernetes release & upgrade notes")
    root = ElementTree.parse(Path(__file__).resolve().parents[1] / "public" / "sitemap.xml")
    urls = [row.text for row in root.findall(".//{*}loc") if "/technologies" in row.text]
    assert len(urls) == 7
    with TestClient(app) as browser:
        directory = browser.get("/technologies")
        for url in urls:
            path = urlsplit(url).path
            response = browser.get(path)
            assert response.status_code == 200
            assert f'<link rel="canonical" href="{url}"' in response.text
            assert "noindex" not in response.headers.get("X-Robots-Tag", "")
            if path != "/technologies":
                assert f'href="{path}"' in directory.text
        tracker = browser.get("/technologies/kubernetes")
        assert "Kubernetes release &amp; upgrade notes" in tracker.text
        assert f'href="{article["url"]}"' in tracker.text
        assert "Publisher excerpt for the interactive reader." not in tracker.text
        assert 'href="/?view=briefing#daily-delivery"' in tracker.text
        assert "schema.org/BreadcrumbList" in tracker.text
        assert browser.get("/technologies/unknown").status_code == 404


def test_mail_health_counts_only_active_opt_ins(archive, monkeypatch):
    now = time.time()
    archive.subscribe("active", "active@example.test", "UTC", now + 3600)
    archive.subscribe("removed", "removed@example.test", "UTC", now + 3600)
    archive.unsubscribe("removed")
    monkeypatch.setenv("FEED_REFRESH_SECRET", "local-seo-test-fixture-only")
    with TestClient(app) as browser:
        assert browser.get("/api/jobs/mail-health").status_code == 401
        response = browser.get("/api/jobs/mail-health", headers={"Authorization": "Bearer local-seo-test-fixture-only"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["active_subscriptions"] == 1
        assert response.json()["due"] == 0


def test_technology_answer_can_cite_exact_official_release_title(archive, monkeypatch):
    release(archive, "headline", "1.34.0", "", title="Kubernetes v1.34.0")
    monkeypatch.setattr(research, "ai_enabled", lambda: True)

    def headline_answer(payload, system, schema, **options):
        source = json.loads(payload)["evidence"][0]
        assert source["record_kind"] == "release" and source["excerpt"] == ""
        return json.dumps({"status": "answered", "limitations": "The release entry has no retained notes.", "claims": [
            {"text": "Kubernetes v1.34.0 was listed as a release.", "kind": "fact", "source_ids": [source["id"]],
             "quotes": [source["title"]]}]})

    monkeypatch.setattr(research, "generate_response", headline_answer)
    with TestClient(app) as browser:
        response = browser.post("/api/intelligence/technologies/kubernetes/ask", json={})
        assert response.status_code == 200
        assert response.json()["answer"]["status"] == "answered"


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
