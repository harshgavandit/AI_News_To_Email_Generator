from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import server
from app.launch_store import connect
from app.sources import BY_ID


def story(source, ident, title, *, minutes=5, description="Publisher excerpt."):
    return {"id": ident, "source": BY_ID[source].group, "source_id": source, "publisher": BY_ID[source].label, "category": "News",
            "kind": "news", "title": title, "description": description, "url": f"https://example.com/{ident}",
            "published_at": (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    store = connect(f"sqlite:///{tmp_path / 'world.db'}")
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.delenv("VERCEL", raising=False)
    for source, rows in {
        "bbc-tech": [story("bbc-tech", "outage-a", "Microsoft 365 outage disrupts Outlook and Teams"),
                     story("bbc-tech", "launch", "New phone goes on sale", minutes=9)],
        "guardian-tech": [story("guardian-tech", "outage-b", "Global Microsoft outage leaves millions without Outlook", minutes=7)],
        "nvidia-newsroom": [story("nvidia-newsroom", "chips", "NVIDIA announces a new accelerator", minutes=25)],
        "techcabal": [story("techcabal", "regional", "Kenya's payments firms expand", minutes=35)],
        "github-blog": [story("github-blog", "release", "GitHub announces release tooling", minutes=40)],
        "cloudflare-status": [story("cloudflare-status", "maintenance", "Scheduled maintenance in Tokyo", minutes=1)],
        "openai-news": [story("openai-news", "ai", "A new model is available", minutes=55)],
    }.items():
        store.ingest(source, rows, True)
    return store, TestClient(server.app)


def test_world_topics_classify_independent_incidents_and_bind_pagination(archive):
    _, client = archive
    response = client.get("/api/news?topic=outages&hours=24&limit=1")
    assert response.status_code == 200
    first = response.json()
    assert first["articles"][0]["topic"] == "outages"
    assert first["total"] == 3
    assert client.get("/api/news", params={"topic": "chips", "hours": 24, "cursor": first["next_cursor"]}).status_code == 400
    assert [a["id"] for a in client.get("/api/news?topic=chips&hours=24").json()["articles"]] == ["chips"]
    assert client.get("/api/news?topic=unsupported").status_code == 422


def test_one_shot_is_recent_varied_and_mail_preview_compatible(archive, monkeypatch):
    store, client = archive
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/api/digest", json={"edition": "world", "hours": 24})
    assert response.status_code == 200, response.text
    payload = response.json()
    digest = payload["digest"]
    assert digest["edition"] == "world"
    assert len(digest["articles"]) == 5
    assert digest["articles"][0]["digest_id"] == "outage-a"
    assert {"outage-a", "chips", "regional", "release", "ai"} == {a["digest_id"] for a in digest["articles"]}
    assert all(a["publisher"] and a["published_at"] and a["url"] for a in digest["articles"])
    assert "Publisher excerpt." in digest["html"] and "https://example.com/chips" in digest["markdown"]
    assert store.get_preview(payload["preview_id"]) == digest


def test_world_release_uses_regional_news_and_official_status_feeds(archive):
    _, client = archive
    sources = {s["id"]: s for s in client.get("/api/sources").json()["sources"]}
    assert sources["rest-of-world"]["coverage"] == "reporting"
    assert sources["techcabal"]["region"] == "Africa"
    assert sources["scmp-tech"]["region"] == "Asia"
    assert sources["cloudflare-status"]["coverage"] == "status"
    assert sources["nvidia-newsroom"]["topic"] == "chips"


def test_front_page_uses_source_attribution_and_edge_cache_only_for_public_views(archive):
    store, client = archive
    store.ingest("latamlist", [story("latamlist", "latam", "Brazilian startups expand into payments")], True)
    store.ingest("hacker-news", [story("hacker-news", "hn", "A new compiler", description="Article URL Comments URL Points: 102")], True)
    store.ingest("bbc-tech", [story("bbc-tech", "future", "A future headline", minutes=-30)], True)

    response = client.get("/api/news?hours=12&limit=12")
    assert "s-maxage=30" in response.headers["Vercel-CDN-Cache-Control"]
    articles = {item["id"]: item for item in response.json()["articles"]}
    assert "future" not in articles
    assert articles["hn"]["coverage"] == "discussion" and articles["hn"]["cleanSummary"] == ""
    assert articles["launch"]["whyItMatters"] == ""
    for suffix, ident in (("region=Africa", "regional"), ("region=LatAm", "latam"), ("q=compiler", "hn")):
        filtered = client.get(f"/api/news?hours=12&{suffix}")
        assert "Vercel-CDN-Cache-Control" not in filtered.headers
        assert [item["id"] for item in filtered.json()["articles"]] == [ident]


def test_scheduler_uses_a_scoped_secret_and_reports_all_feed_failures(archive, monkeypatch):
    _, client = archive
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setenv("FEED_REFRESH_SECRET", "dedicated-test-refresh-secret")
    monkeypatch.setattr(server, "refresh_sources", lambda store: [{"enabled": True, "available": False}])
    assert client.get("/api/jobs/refresh").status_code == 401
    headers = {"Authorization": "Bearer dedicated-test-refresh-secret"}
    assert client.post("/api/admin/sources", headers=headers).status_code == 401
    assert client.get("/api/jobs/refresh", headers=headers).status_code == 503
