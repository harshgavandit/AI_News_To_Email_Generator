from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import news, server
from app.headlines import build_headlines
from app.launch_store import Store
from app.sources import BY_ID
from app.story_coverage import compare_coverage


def article(ident, provider, title, age, now):
    source = BY_ID[provider]
    return {"id": ident, "source_id": source.id, "source": source.group, "publisher": source.label,
            "kind": source.kind, "category": "Technology", "title": title, "description": "Publisher excerpt.",
            "url": f"https://{source.hosts[0]}/{ident}", "published_at": (now - timedelta(hours=age)).isoformat()}


def test_headlines_prioritize_material_changes_without_static_featured_stories():
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
    assert result["coverage"] == []


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


def test_headlines_leave_room_for_other_regions_during_an_apac_news_spike():
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    rows = [article("asia", "scmp-tech", "Chipmaker CEO resigns", 1, now),
            article("india", "inc42", "Indian software group appoints new CEO", 2, now),
            article("australia", "itnews-au", "Australian provider searches for a CEO successor", 3, now),
            article("europe", "tech-eu", "A European startup secures a customer", 10, now),
            article("africa", "itweb", "South African telecom operator expands network", 16, now)]
    assert {a["id"] for a in build_headlines(rows, now=now, limit=3)["articles"]} == {"asia", "europe", "africa"}


def test_developing_story_exposes_comparison_metadata_and_sampled_source_count(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'developing.db'}")
    monkeypatch.setattr(server, "get_store", lambda: store)
    now = datetime.now(UTC)
    title = "MongoDB acquires Firebolt to expand real time analytics"
    providers = ("microsoft-source", "microsoft-official-blog", "bbc-tech", "the-verge", "ars-technica",
                 "wired", "tech-eu", "9to5google")
    rows = [article(f"report-{i}", provider, title, i + 1, now) for i, provider in enumerate(providers)]
    rows[2]["description"] = "<p>A short publisher-supplied excerpt.</p>"
    for row in rows:
        store.ingest(row["source_id"], [row], True)
    response = TestClient(server.app).get("/api/headlines")
    assert response.status_code == 200
    feature, = response.json()["coverage"]
    assert feature["id"] == feature["article_id"] == rows[0]["id"]
    assert feature["source_count"] == 7
    assert feature["source_count_basis"] == "distinct_publisher_families_in_sample"
    assert [source["article_id"] for source in feature["sources"]] == [row["id"] for row in rows[:6] if row != rows[1]]
    official, reporting, *_ = feature["sources"]
    assert official["coverage"] == "publisher" and official["publisher_family"] == "microsoft"
    assert reporting == {"publisher": rows[2]["publisher"], "label": title, "url": rows[2]["url"],
                         "article_id": rows[2]["id"], "published_at": rows[2]["published_at"], "date_precision": None,
                         "coverage": "reporting", "language": "en", "publisher_family": "bbc-tech",
                         "excerpt": "A short publisher-supplied excerpt."}
    store.engine.dispose()


def test_article_comparison_keeps_highest_ranked_report_per_publisher_family():
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    title = "Microsoft launches cloud analytics platform for enterprise customers"
    official = article("first", "microsoft-source", title, 2, now)
    blog = article("second", "microsoft-official-blog", title, 3, now)
    independent = article("report", "bbc-tech", title, 1, now)
    assert [row["id"] for row in compare_coverage(official, [blog, independent])] == ["report"]
    comparison = compare_coverage(independent, [blog, official])
    assert [row["id"] for row in comparison] == ["first"]
    assert comparison[0]["related_reason"] == "Closely matching headlines"


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
