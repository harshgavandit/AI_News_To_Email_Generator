from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest

from app import discovery_health, news, server
from app.coverage import topic_for
from app.launch_store import Store
from app.news_sitemap import parse_xml, read_news_sitemap
from app.publisher_listing import article_metadata, read_listing
from app.signals import priority_signals
from app.sources import BY_ID


def story(ident="incident", source="google-threat-intelligence", **overrides):
    feed = BY_ID[source]
    return dict(id=ident, title="Google reports autonomous exploit attacks", description="Publisher reports exploitation.",
        source=feed.group, source_id=source, publisher=feed.label, kind=feed.kind, category="News",
        url=f"https://{feed.hosts[0]}/{ident}", published_at=datetime.now(UTC).isoformat(), **overrides)


def sitemap(url="https://venturebeat.com/security/incident", title="AI exploit investigation", date=None):
    date = date or datetime.now(UTC).isoformat()
    return f'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
    xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url><loc>{url}</loc>
    <news:news><news:title>{title}</news:title><news:publication_date>{date}</news:publication_date></news:news>
    </url></urlset>'''.encode()


def test_sitemap_preserves_original_title_date_and_deduplicates_rss(tmp_path, monkeypatch):
    source = BY_ID["venturebeat-news-index"]
    items, state = read_news_sitemap(source, lambda _: sitemap())
    assert state["available"] and state["observed_entries"] == 1
    item, = items
    assert item["description"] == "" and topic_for(item) == "security"
    store = Store(f"sqlite:///{tmp_path / 'archive.db'}")
    store.ingest(source.id, items, True)
    store.ingest("venturebeat", [dict(item, description="The publisher supplied an excerpt.")], True)
    rows = store.page(hours=24, source="all", query="exploit", kind="all", publisher="", limit=5, cursor=None)
    assert rows["total"] == 1
    assert set(store.article_feed_ids(item["id"])) == {"venturebeat", source.id}


@pytest.mark.parametrize("body", [b"<!DOCTYPE x><urlset/>", b'<!ENTITY x "oops"><urlset/>'])
def test_sitemap_rejects_document_type_and_entity_expansion(body):
    with pytest.raises(ValueError):
        parse_xml(body)


def test_sitemap_never_follows_unreviewed_index_urls():
    source = BY_ID["bbc-news-index"]
    allowed = "https://www.bbc.com" + source.sitemap_paths[0]
    index = f'''<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://127.0.0.1/private</loc></sitemap>
      <sitemap><loc>https://www.bbc.com/arbitrary.xml</loc></sitemap>
      <sitemap><loc>{allowed}</loc></sitemap></sitemapindex>'''.encode()
    fetched = []

    def fetch(url):
        fetched.append(url)
        return index if url == source.url else sitemap("https://www.bbc.com/news/articles/example", "AI startup expands")

    items, _ = read_news_sitemap(source, fetch)
    assert len(items) == 1 and fetched == [source.url, allowed]
    bad, _ = read_news_sitemap(BY_ID["venturebeat-news-index"], lambda _: sitemap("https://attacker.example/story"))
    assert not bad
    undated = sitemap().replace(b"publication_date", b"lastmod")
    assert not read_news_sitemap(BY_ID["venturebeat-news-index"], lambda _: undated)[0]


def test_reviewed_http_links_upgrade_to_https_and_keep_references(monkeypatch):
    feed = b'''<rss version="2.0"><channel><title>Security</title><item><title>Security research</title>
      <link>http://security.googleblog.com/research</link><pubDate>Mon, 16 Nov 2026 12:00:00 GMT</pubDate>
      <description><![CDATA[An investigation. <a href="https://cloud.google.com/blog/report">Original research</a>
      <a href="javascript:alert(1)">Unsafe</a>]]></description></item></channel></rss>'''
    monkeypatch.setattr(news, "fetch_bytes", lambda _: feed)
    items, status = news.read_feed(BY_ID["google-security"])
    assert status["available"]
    assert items[0]["url"] == "https://security.googleblog.com/research"
    assert items[0]["references"] == [{"url": "https://cloud.google.com/blog/report", "label": "Original research"}]
    assert topic_for(story()) == "security"


def test_listing_respects_robots_and_skips_archived_metadata():
    source = BY_ID["moneycontrol-it"]
    url = "https://www.moneycontrol.com/news/business/information-technology/company.html"
    fetched = []
    body = f'''<script type="application/ld+json">{{"@type":"NewsArticle","headline":"Chip startup raises capital",
        "datePublished":"{datetime.now(UTC).isoformat()}","description":"A publisher metadata excerpt."}}</script>'''.encode()

    def fetch(link):
        fetched.append(link)
        if link.endswith("robots.txt"):
            return b"User-agent: *\nDisallow: /private\n"
        return f'<a href="{url}">Story</a><a href="https://attacker.example/a.html">Unsafe</a>'.encode() if link == source.url else body

    items, state = read_listing(source, fetch)
    assert state["available"] and len(items) == 1 and fetched[-1] == url
    fetched.clear()
    assert read_listing(source, fetch, known_urls={url})[1]["available"]
    assert url not in fetched
    with pytest.raises(ValueError):
        read_listing(source, lambda _: b"User-agent: *\nDisallow: /\n")


def test_publisher_json_with_literal_body_newlines_keeps_only_metadata():
    body = ('<script type="application/ld+json">{"@type":"NewsArticle",'
            '"headline":"Publisher headline","datePublished":"' + datetime.now(UTC).isoformat() + '",'
            '"description":"Public description.","articleBody":"Unpublished body\ncontinues here"}</script>').encode()
    item = article_metadata(body, "https://www.moneycontrol.com/article.html", BY_ID["moneycontrol-it"])
    assert item["title"] == "Publisher headline" and item["description"] == "Public description."
    assert "Unpublished" not in str(item)


def test_archive_checks_and_coverage_explain_missing_sources_without_fetching(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'health.db'}")
    article = story()
    store.ingest("google-threat-intelligence", [article], True, diagnostics={"observed": 20, "rejected": 3})
    linked = story("community", "hacker-news")
    linked["original_url"] = "https://venturebeat.com/security/original"
    linked["references"] = [{"url": "https://venturebeat.com/security/cited-only"}]
    store.ingest("hacker-news", [linked], True)
    monkeypatch.setattr(discovery_health, "get_store", lambda: store)
    client = TestClient(server.app)
    assert client.get("/api/discovery/check", params={"url": article["url"]}).json()["status"] == "indexed"
    assert client.get("/api/discovery/check", params={"url": linked["original_url"]}).json()["status"] == "indexed"
    assert not store.lookup_url("https://venturebeat.com/security/cited-only")
    assert client.get("/api/discovery/check", params={"url": "https://unknown.example/story"}).json()["status"] == "unsupported_source"
    report = client.get("/api/discovery/coverage").json()
    feed = next(feed for feed in report["feeds"] if feed["id"] == "google-threat-intelligence")
    assert feed["observed_entries"] == 20 and feed["rejected_entries"] == 3
    assert next(topic for topic in report["topics"] if topic["id"] == "security")["articles_24h"] == 2


def test_priority_signals_include_primary_advisories_but_exclude_old_and_community():
    primary = story()
    old = {**story("old", "securityweek"), "published_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}
    community = story("community", "dev-security")
    duplicate = story("same-publisher")
    result = priority_signals([primary, old, community, duplicate])
    assert len(result["articles"]) == 1
    assert result["articles"][0]["signal_type"] == "security"
    assert "not independent verification" in result["basis"]
