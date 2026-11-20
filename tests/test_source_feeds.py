from datetime import UTC, datetime
from email.utils import format_datetime
from html import escape

from app import news
from app.coverage import public_article
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


def test_official_release_feed_keeps_version_only_titles_and_restricts_repository_paths(monkeypatch):
    source = BY_ID["uv-releases"]
    monkeypatch.setattr(news, "fetch_bytes", lambda _: feed(
        ("0.13.8", "https://github.com/astral-sh/uv/releases/tag/0.13.8", ()),
        ("Other project", "https://github.com/unreviewed/other/releases/tag/0.13.8", ()),
    ))
    rows, status = news.read_feed(source)
    assert status["available"] and status["coverage"] == "release"
    assert [item["title"] for item in rows] == ["uv 0.13.8"]


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


def test_latitude_media_keeps_technology_headlines_without_video_metadata(monkeypatch):
    content = feed(
        ("Can AI data centers ease the power crunch?", "https://www.youtube.com/watch?v=D7D1CPOoub4", ()),
        ("Congress debates electricity prices", "https://www.youtube.com/watch?v=hIoTWnAekCc", ()),
    ).replace(b"</item>", b"<description>Publisher notes and a sponsor message.</description></item>")
    monkeypatch.setattr(news, "fetch_bytes", lambda _: content)

    (article,), status = news.read_feed(BY_ID["latitude-media"])
    card = public_article(article)
    assert status["available"] and status["rejected_entries"] == 1
    assert card["sourceUrl"] == "https://www.youtube.com/watch?v=D7D1CPOoub4"
    assert card["reading_access"]["mode"] == "headline_only"
    assert not card["has_excerpt"] and "thumbnail_url" not in card


def test_circuit_keeps_gulf_tech_investment_and_filters_general_business(monkeypatch):
    content = feed(
        ("Gulf investors back a new data center", "https://circuit.news/2026/11/19/data-center", ()),
        ("Property developer opens a new golf resort", "https://circuit.news/2026/11/19/golf-resort", ()),
    )
    monkeypatch.setattr(news, "fetch_bytes", lambda _: content)
    (article,), status = news.read_feed(BY_ID["the-circuit-tech"])
    assert status["available"] and status["rejected_entries"] == 1
    assert public_article(article)["region_id"] == "MENA"
    assert BY_ID["wired-es"].publisher_family == BY_ID["wired"].publisher_family


def test_curiosity_company_sources_use_reviewed_rss_or_robot_rules(monkeypatch):
    assert BY_ID["meta-engineering"].url == "https://engineering.fb.com/feed/"
    assert BY_ID["meta-engineering"].integration == "rss"
    assert BY_ID["meta-engineering"].kind == "engineering"
    assert BY_ID["razorpay-engineering"].url == "https://engineering.razorpay.com/feed"
    assert BY_ID["razorpay-engineering"].require_english
    assert BY_ID["medium-gordicaleksa"].url == "https://gordicaleksa.medium.com/feed"
    assert BY_ID["medium-gordicaleksa"].require_english
    assert BY_ID["stripe-engineering"].integration == "publisher-metadata"
    assert BY_ID["uber-engineering"].integration == "publisher-metadata"
    assert BY_ID["stripe-engineering"].article_paths == ("/blog/",)
    assert BY_ID["uber-engineering"].article_paths == ("/us/en/blog/",)
    assert BY_ID["uber-engineering"].require_english

    source = BY_ID["stripe-engineering"]
    calls = []
    article_url = "https://stripe.com/blog/engineering/zero-downtime-migrations"
    published = datetime.now(UTC).isoformat()
    article = f'''<html><head>
      <meta property="og:title" content="How we built zero-downtime migrations">
      <meta property="article:published_time" content="{published}">
      <meta name="description" content="The infrastructure team explains the migration architecture and reliability safeguards used for production databases.">
      <script type="application/ld+json">{{"@type":"BlogPosting","headline":"How we built zero-downtime migrations","datePublished":"{published}","description":"The infrastructure team explains the migration architecture and reliability safeguards used for production databases."}}</script>
      </head><body></body></html>'''.encode()

    def fake_fetch(url):
        calls.append(url)
        if url == "https://stripe.com/robots.txt":
            return b"User-agent: *\nAllow: /blog/\nDisallow: /blog/private/\n"
        if url == source.url:
            return f'<a href="{article_url}">Engineering article</a>'.encode()
        if url == article_url:
            return article
        raise AssertionError(f"unexpected fetch URL: {url}")

    monkeypatch.setattr(news, "fetch_bytes", fake_fetch)
    rows, status = news.read_feed(source)

    assert status["available"] is True
    assert [row["title"] for row in rows] == ["How we built zero-downtime migrations"]
    assert rows[0]["url"] == article_url
    assert all("stripe.com" in url for url in calls)
    assert calls.count(article_url) == 1
