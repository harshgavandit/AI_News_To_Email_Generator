"""Public RSS feeds: valid RSS 2.0, links to publishers, escaping, caching and validation."""
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

from fastapi.testclient import TestClient
import pytest

from app import feeds
from app.launch_store import get_store
from app.sources import BY_ID


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'feeds.sqlite'}")
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://getinformdaily.com")
    monkeypatch.delenv("VERCEL", raising=False)
    store = get_store()
    store.migrate()
    feeds._feed_cache.clear()
    from app.server import app
    yield TestClient(app), store
    feeds._feed_cache.clear()


def add(store, ident, feed, title, excerpt, *, path=None, hours_ago=1, category="ai"):
    source = BY_ID[feed]
    row = {"id": ident, "source": source.group, "source_id": feed, "publisher": source.label, "kind": source.kind,
           "category": category, "url": f"https://{source.hosts[0]}{path or '/' + ident}",
           "published_at": (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(), "title": title,
           "description": excerpt}
    store.ingest(feed, [row], True)
    return row


def parse(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/rss+xml; charset=utf-8"
    root = ElementTree.fromstring(response.content)
    assert root.tag == "rss" and root.get("version") == "2.0"
    channel = root.find("channel")
    return channel, channel.findall("item")


def test_latest_feed_links_to_publishers_and_escapes_publisher_text(client):
    http, store = client
    add(store, "feed-a", "kubernetes-blog", "Kubernetes & scaling <limits>",
        "The release improves scheduling for large clusters & batch jobs.", path="/blog/2026/11/24/release/")
    channel, items = parse(http.get("/feeds/latest.xml"))
    assert channel.findtext("title") == "Latest technology news | Informa AI"
    self_link = channel.find("{http://www.w3.org/2005/Atom}link")
    assert self_link.get("href") == "https://getinformdaily.com/feeds/latest.xml" and self_link.get("rel") == "self"
    item = items[0]
    raw = http.get("/feeds/latest.xml").text
    assert "&amp;" in raw and "<limits>" not in raw  # publisher text is escaped, never markup
    assert item.findtext("title").startswith("Kubernetes & scaling")
    assert item.findtext("link") == "https://kubernetes.io/blog/2026/11/24/release/"
    assert item.findtext("guid") == "informa:feed-a"
    assert item.findtext("description").endswith(f"— {BY_ID['kubernetes-blog'].label}")
    assert item.findtext("{http://purl.org/dc/elements/1.1/}creator") == BY_ID["kubernetes-blog"].label
    assert datetime.strptime(item.findtext("pubDate"), "%a, %d %b %Y %H:%M:%S %z") <= datetime.now(UTC)


def test_feeds_answer_conditional_requests_and_are_edge_cached(client):
    http, store = client
    add(store, "feed-b", "kubernetes-blog", "Cluster autoscaling notes", "Notes on autoscaling.")
    first = http.get("/feeds/latest.xml")
    assert first.headers["cache-control"] == "public, max-age=600"
    assert "s-maxage=900" in first.headers["vercel-cdn-cache-control"]
    again = http.get("/feeds/latest.xml", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b""


def test_topic_technology_and_search_feeds(client):
    http, store = client
    add(store, "feed-c", "kubernetes-releases", "Release v1.36.0", "Kubernetes v1.36.0 adds features.",
        path="/kubernetes/kubernetes/releases/tag/v1.36.0", category="software")
    add(store, "feed-d", "techcrunch", "A quantum chip milestone", "Researchers describe a new chip.", category="chips")
    _, tech_items = parse(http.get("/feeds/technology/kubernetes.xml"))
    assert "Release v1.36.0" in [item.findtext("title") for item in tech_items]
    channel, searched = parse(http.get("/feeds/search.xml", params={"q": "quantum chip"}))
    assert [item.findtext("title") for item in searched] == ["A quantum chip milestone"]
    assert channel.findtext("title") == "Search: quantum chip | Informa AI"
    assert parse(http.get("/feeds/topic/ai.xml"))[0].findtext("title") == "AI & Machine Learning | Informa AI"
    assert http.get("/feeds/topic/not-a-topic.xml").status_code == 404
    assert http.get("/feeds/technology/not-a-tech.xml").status_code == 404
    assert http.get("/feeds/search.xml", params={"q": "!!"}).status_code == 422
    assert http.get("/feeds/search.xml", params={"q": "x" * 81}).status_code == 422
    assert http.get("/feeds/search.xml").status_code == 422


def test_curiosity_feed_links_to_card_pages_newest_first(client, monkeypatch):
    from app import curiosity_api

    cards = [{"id": "older", "title": "Old classic", "summary": "A classic.", "publisher": "ACM", "year": 2016, "theme": "databases"},
             {"id": "newer", "title": "Recent postmortem", "summary": "What failed.", "publisher": "GitHub",
              "published_at": "2026-10-14T00:00:00+00:00", "theme": "reliability"}]
    monkeypatch.setattr(curiosity_api, "curiosity_shelf", lambda: {"cards": cards})
    _, items = parse(client[0].get("/feeds/curiosity.xml"))
    assert [item.findtext("link") for item in items] == ["https://getinformdaily.com/cards/newer",
                                                        "https://getinformdaily.com/cards/older"]
    assert items[0].findtext("category")


def test_feed_directory_lists_every_feed_and_pages_advertise_them(client):
    listing = client[0].get("/api/feeds").json()
    assert listing["latest"]["path"] == "/feeds/latest.xml"
    assert {"ai", "security"} <= {topic["id"] for topic in listing["topics"]}
    assert "kubernetes" in {tech["id"] for tech in listing["technologies"]}
    from pathlib import Path
    public = Path(__file__).resolve().parents[1] / "public"
    assert 'type="application/rss+xml"' in (public / "index.html").read_text(encoding="utf-8")
    assert 'href="/feeds/curiosity.xml"' in (public / "curiosity.html").read_text(encoding="utf-8")


def test_story_feeds_are_english_by_default(client):
    http, store = client
    add(store, "feed-en", "techcrunch", "Chip startup raises a new round", "The company makes accelerators.")
    row = add(store, "feed-fr", "techcrunch", "Une start-up de puces lève des fonds pour ses accélérateurs",
              "La société fabrique des accélérateurs pour centres de données.")
    titles = lambda response: [item.findtext("title") for item in parse(response)[1]]  # noqa: E731
    english = titles(http.get("/feeds/latest.xml"))
    assert "Chip startup raises a new round" in english
    assert row["title"] not in english
    assert row["title"] in titles(http.get("/feeds/latest.xml", params={"language": "all"}))
    assert http.get("/feeds/latest.xml", params={"language": "klingon"}).status_code == 422
    assert feeds.latin_headline("Release v1.36.0") and feeds.latin_headline("Déjà vu in Zürich")
    assert not feeds.latin_headline("CrowdStrike以439億美元併購Zscaler，創下資安界交易紀錄")
