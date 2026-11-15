from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import news, server
from app.headlines import active_coverage, build_headlines
from app.launch_store import Store
from app.sources import BY_ID


def article(ident, provider, title, age, now):
    source = BY_ID[provider]
    return {"id": ident, "source_id": source.id, "source": source.group, "publisher": source.label,
            "kind": source.kind, "category": "Technology", "title": title, "description": "Publisher excerpt.",
            "url": f"https://{source.hosts[0]}/{ident}", "published_at": (now - timedelta(hours=age)).isoformat()}


def test_headlines_prioritize_material_changes_and_expire_the_reviewed_story():
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    stories = [article("lead", "cbs-tech", "Nvidia CEO transition adds a new chapter", 36, now),
               article("policy", "itnews-au", "Australia enacts new export controls for semiconductors", 12, now),
               article("breach", "itweb", "Ransomware attack exposes customer data", 4, now),
               article("minor", "tech-eu", "An interview with a local founder", 1, now),
               article("stale", "indian-express-tech", "A CEO resigns after an investigation", 85, now),
               article("opinion", "hacker-news", "CEO resigns following deal", 1, now),
               article("shopping", "tecnoblog", "Black Friday best deals for phones", 1, now)]
    result = build_headlines(stories, now=now, limit=3)
    assert [s["id"] for s in result["articles"]] == ["breach", "policy", "minor"]
    lead, = result["coverage"]
    assert "Nikesh Arora" in lead["summary"] and "interim CEO" in lead["summary"]
    assert any(s["publisher"] == "NVIDIA Newsroom" for s in lead["sources"])
    assert not active_coverage(now - timedelta(days=3))
    assert not active_coverage(now + timedelta(days=7))


def test_headlines_endpoint_uses_enabled_archive_sources(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'headlines.db'}")
    monkeypatch.setattr(server, "get_store", lambda: store)
    now = datetime.now(UTC)
    store.ingest("tech-eu", [article("capital", "tech-eu", "An enterprise startup raises a new round", 1, now)], True)
    store.ingest("itweb", [article("net", "itweb", "A telecom operator discloses a breach", 1, now)], True)
    store.enable("itweb", False)
    response = TestClient(server.app).get("/api/headlines")
    assert response.status_code == 200
    assert [a["id"] for a in response.json()["articles"]] == ["capital"]
    assert response.headers["Vercel-CDN-Cache-Control"] == "public, s-maxage=30"


def test_general_publisher_feed_keeps_only_tech_and_original_links(monkeypatch):
    feed = b"""<rss version="2.0"><channel><title>Fixture</title>
    <item><title>Nvidia begins CEO search</title><link>https://www.axios.com/tech-story?utm_source=rss</link>
      <pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>
    <item><title>Administration discusses a foreign-policy proposal</title><link>https://www.axios.com/general</link>
      <pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>
    <item><title>Microsoft ships a product</title><link>https://elsewhere.example/story</link>
      <pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""
    clock = datetime(2026, 11, 15, 12, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock

    monkeypatch.setattr(news, "datetime", Clock)
    monkeypatch.setattr(news, "fetch_bytes", lambda url: feed)
    stories, status = news.read_feed(BY_ID["axios-tech"])
    assert status["available"]
    assert [story["url"] for story in stories] == ["https://www.axios.com/tech-story"]
