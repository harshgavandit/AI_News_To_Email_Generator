from datetime import UTC, datetime
from email.utils import format_datetime
from html import escape

from app import news
from app.sources import BY_ID


def feed(*entries):
    published = format_datetime(datetime.now(UTC), usegmt=True)
    items = []
    for title, link, tags in entries:
        categories = "".join(f"<category>{escape(tag)}</category>" for tag in tags)
        items.append(f"<item><title>{escape(title)}</title><link>{escape(link)}</link>"
                     f"<pubDate>{published}</pubDate>{categories}</item>")
    return f'<rss version="2.0"><channel><title>Test</title>{"".join(items)}</channel></rss>'.encode()


def test_scope_keeps_publisher_url_and_ordered_category_labels(monkeypatch):
    content = feed(
        ("Debian releases a point update", "/news/debian-stable.html?wt_mc=rss&channel=debian",
         ("Open Source", "Software", "Open Source")),
        ("heise-Angebot: Community conference tickets", "/news/event.html", ()),
        ("Outside the news section", "/ratgeber/tutorial.html", ()),
        ("Malicious feed entry", "https://external.example/news/story", ()),
    )
    monkeypatch.setattr(news, "fetch_bytes", lambda _: content)

    rows, status = news.read_feed(BY_ID["heise-online"])

    story, = rows
    assert status["available"] and status["language"] == "de"
    assert story["url"] == "https://www.heise.de/news/debian-stable.html?channel=debian"
    assert story["category"] == "Open Source | Software"


def test_filtered_feed_is_available_and_host_mismatch_fails(monkeypatch):
    scope = BY_ID["xataka-mx"]
    monkeypatch.setattr(news, "fetch_bytes", lambda _: feed(
        ("Gift guide", "https://www.xataka.com.mx/seleccion/guide", ()),
    ))
    rows, status = news.read_feed(scope)
    assert rows == [] and status["available"] and status["count"] == 0

    monkeypatch.setattr(news, "fetch_bytes", lambda _: feed(
        ("Unexpected link", "https://other.example/story", ()),
    ))
    rows, status = news.read_feed(scope)
    assert rows == [] and not status["available"] and status["error"] == "no_eligible_entries"


def test_valid_empty_feed_and_html_response_have_different_health(monkeypatch):
    source = BY_ID["arxiv-ai"]
    monkeypatch.setattr(news, "fetch_bytes", lambda _: feed())
    rows, status = news.read_feed(source)
    assert rows == [] and status["available"] and status["coverage"] == "preprint"

    for invalid_response in (b"", b"<html><body>Upstream error</body></html>"):
        monkeypatch.setattr(news, "fetch_bytes", lambda _, body=invalid_response: body)
        rows, status = news.read_feed(source)
        assert rows == [] and not status["available"] and status["error"] == "invalid_feed"


def test_medium_uses_the_same_id_across_feeds_without_losing_publisher_link(monkeypatch):
    def fixture(url):
        return feed(("Understanding distributed transactions", url, ("software",))).replace(
            b"</item>", b"<guid>https://medium.com/p/abc123def456</guid>"
            b"<description>Compare isolation levels. Continue reading on Medium.</description></item>",
        )

    responses = iter([
        fixture("https://medium.com/codex/transactions-abc123def456?source=rss-a"),
        fixture("https://author.medium.com/transactions-abc123def456?source=rss-b&sk=private"),
    ])
    monkeypatch.setattr(news, "fetch_bytes", lambda _: next(responses))
    (first,), _ = news.read_feed(BY_ID["medium-codex"])
    (second,), _ = news.read_feed(BY_ID["medium-programming"])
    assert first["id"] == second["id"]
    assert first["url"] == "https://medium.com/codex/transactions-abc123def456"
    assert second["url"] == "https://author.medium.com/transactions-abc123def456"
    assert second["description"] == "Compare isolation levels."

    monkeypatch.setattr(news, "fetch_bytes", lambda _: fixture("https://medium.com.evil.example/abc123def456"))
    rows, status = news.read_feed(BY_ID["medium-programming"])
    assert rows == [] and not status["available"]
