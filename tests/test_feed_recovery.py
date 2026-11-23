import socket
import ssl
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException

from app import ingestion, news, server
from app.launch_store import Store
from app.sources import BY_ID, DEFAULT_SOURCES


def test_configured_pause_overrides_preexisting_enabled_state(tmp_path, monkeypatch):
    source = replace(BY_ID["bbc-tech"], enabled=False)
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    store = Store(f"sqlite:///{tmp_path / 'feed-recovery.db'}")
    store.ingest(source.id, [], False, "access_denied")
    assert store.source_state()[source.id]["enabled"] is True
    monkeypatch.setattr(ingestion, "read_feed", lambda *args, **kwargs: pytest.fail("Paused source fetched"))

    now = datetime.now(UTC)
    assert ingestion.sweep_plan(store.source_state(), ingestion.latest_sweep(now), now) == (set(), {})
    assert ingestion.refresh_plan(store.source_state(), only=source.id) == []
    feed, = ingestion.refresh_sources(store)
    assert feed["freshness"] == "paused"
    assert feed["next_check_at"] is None
    assert ingestion.feed_freshness([feed])["counts"]["enabled"] == 0


def test_owner_cannot_enable_a_connector_paused_in_the_registry(monkeypatch):
    source = BY_ID["tech-in-asia"]
    monkeypatch.setattr(server, "BY_ID", {source.id: replace(source, enabled=False)})
    monkeypatch.setenv("ADMIN_TOKEN", "owner-key-for-tests-0123456789abcdef0123")
    monkeypatch.setattr(server, "source_store", lambda: pytest.fail("Paused source was changed"))
    with pytest.raises(HTTPException) as caught:
        server.update_source(source.id, server.SourceUpdate(enabled=True), "Bearer owner-key-for-tests-0123456789abcdef0123")
    assert caught.value.status_code == 409


def test_paused_connectors_keep_reasons_and_coverage_alternatives():
    paused = ("tech-in-asia", "hashnode-discover", "venturebeat", "venturebeat-news-index", "moneycontrol-it", "robohub")
    assert all(not BY_ID[key].enabled and BY_ID[key].pause_reason for key in paused)
    active = [source for source in DEFAULT_SOURCES if source.enabled]
    assert len(active) >= 501
    for key in ("govtech-singapore", "open-robotics-discourse", "techxplore-robotics",
                "release-mistral-vibe", "release-pytorch-executorch", "release-langflow"):
        replacement = BY_ID[key]
        assert [source.id for source in active if source.url == replacement.url] == [key]
    for key in ("tnglobal", "hashnode", "crossref-nature-mi", "nature-machine-intelligence",
                "moneycontrol-tech", "moneycontrol-news-index", "techxplore-robotics"):
        assert BY_ID[key].enabled


@pytest.mark.parametrize(("error", "cause", "code"), [
    (TimeoutError(), None, "fetch_timeout"),
    (httpx.ReadTimeout("read timeout"), None, "fetch_timeout"),
    (httpx.ConnectError("cannot resolve"), socket.gaierror(), "dns_failed"),
    (httpx.ConnectError("certificate error"), ssl.SSLError(), "tls_failed"),
    (httpx.ConnectError("connection refused"), None, "connection_failed"),
])
def test_rss_transport_failures_keep_an_actionable_safe_code(monkeypatch, error, cause, code):
    def fail(_):
        raise error from cause

    monkeypatch.setattr(news, "fetch_bytes", fail)
    rows, state = news.read_feed(BY_ID["nature-machine-intelligence"])
    assert not rows and not state["available"]
    assert state["error"] == code


def test_medium_custom_domain_blogs_read_through_medium_feeds():
    """Medium rate-limits custom-domain feeds from cloud hosts; medium.com/feed/<publication> is served."""
    repaired = {"hotstar-tech": ("hotstar", "blog.hotstar.com"),
                "klarna-engineering": ("klarna-engineering", "engineering.klarna.com"),
                "cookpad-sourcediving": ("sourcediving", "sourcediving.com"),
                "dream11-engineering": ("dream11-tech-blog", "blog.dream11engineering.com")}
    for key, (slug, domain) in repaired.items():
        source = BY_ID[key]
        assert source.enabled and source.url == f"https://medium.com/feed/{slug}"
        assert source.group == "medium" and set(source.hosts) == {"medium.com", domain}
        assert source.publisher_family == key, "each blog stays its own publisher"


def test_feed_repairs_and_pauses_from_the_november_23_review():
    assert BY_ID["graphics-programming-weekly"].url == "https://www.jendrikillner.com/index.xml"
    assert BY_ID["doordash-blog"].url == "https://careersatdoordash.com/blog/category/engineering/feed/"
    for key in ("hpcwire", "uktn", "stripe-engineering"):
        assert not BY_ID[key].enabled and BY_ID[key].pause_reason
    stripe = [source for source in DEFAULT_SOURCES if source.enabled and source.url == "https://stripe.com/blog/feed.rss"]
    assert [source.id for source in stripe] == ["engineering-stripe"], "Stripe's blog stays covered"


def test_lobsters_keeps_the_discussion_link_instead_of_the_external_article(monkeypatch):
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Lobsters</title><link>https://lobste.rs/</link>
      <item><title>GitHub Actions accepts invalid YAML</title>
      <link>https://example.net/til/post/github-actions-accepts-invalid-yaml/</link>
      <guid>https://lobste.rs/s/leqwqu</guid><pubDate>Sun, 22 Nov 2026 15:49:18 -0600</pubDate>
      <comments>https://lobste.rs/s/leqwqu/github_actions_accepts_invalid_yaml</comments>
      <category>programming</category></item></channel></rss>"""
    monkeypatch.setattr(news, "fetch_bytes", lambda url: rss)
    items, status = news.read_feed(BY_ID["lobsters"])
    assert status["available"] is True
    assert [item["url"] for item in items] == ["https://lobste.rs/s/leqwqu/github_actions_accepts_invalid_yaml"]
