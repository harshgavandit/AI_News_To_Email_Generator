"""Feed health states and Curiosity Cards that outlive the 90-day archive."""
from datetime import UTC, datetime, timedelta

from app import curiosity
from app.ingestion import source_health
from app.launch_store import Store

NOW = datetime(2026, 11, 22, 12, tzinfo=UTC)


def feed(**values):
    base = {"enabled": True, "available": True, "last_success": NOW.isoformat(), "content_status": "recent"}
    return {**base, **values}


def test_quiet_feed_is_healthy_not_failed():
    assert source_health(feed(), NOW) == "active"
    assert source_health(feed(content_status="quiet"), NOW) == "quiet"
    # No posts for 90 days or nothing retained at all is still a working feed.
    assert source_health(feed(content_status="no_retained_content"), NOW) == "quiet"


def test_recent_failures_are_temporary_and_lasting_ones_are_broken():
    recently = (NOW - timedelta(days=2)).isoformat()
    long_ago = (NOW - timedelta(days=40)).isoformat()
    three_weeks = (NOW - timedelta(days=21)).isoformat()
    assert source_health(feed(available=False, error="upstream_unavailable", last_success=recently), NOW) == "temporarily_unavailable"
    assert source_health(feed(available=False, error="feed_not_found", last_success=recently), NOW) == "temporarily_unavailable"
    assert source_health(feed(available=False, error="fetch_timeout", last_success=three_weeks), NOW) == "temporarily_unavailable"
    assert source_health(feed(available=False, error="feed_not_found", last_success=three_weeks), NOW) == "broken"
    assert source_health(feed(available=False, error="fetch_timeout", last_success=long_ago), NOW) == "broken"
    assert source_health(feed(available=False, error="dns_failed", last_success=None), NOW) == "broken"
    assert source_health(feed(available=False, error="rate_limited", last_success=None), NOW) == "temporarily_unavailable"
    assert source_health(feed(enabled=False), NOW) == "paused"
    assert source_health(feed(available=None, last_success=None), NOW) == "pending"


def test_catalog_reports_health_for_every_source(tmp_path):
    from app.ingestion import source_catalog
    store = Store(f"sqlite:///{(tmp_path / 'health.sqlite').as_posix()}")
    catalog = source_catalog(store)
    assert {feed["health"] for feed in catalog} <= {"active", "quiet", "temporarily_unavailable", "broken", "pending", "paused"}
    assert all(feed["health"] == "paused" for feed in catalog if not feed["enabled"])


def test_reading_levels_follow_what_the_source_says():
    def card(ident):
        return curiosity.curiosity_article(ident)
    assert curiosity.card_level(card("gaffer-game-networking")) == "introductory"
    assert curiosity.card_level(card("flash-attention-eli5")) == "introductory"
    assert curiosity.card_level(card("naughty-dog-fibers")) == "advanced"
    assert curiosity.card_level(card("google-spanner")) == "advanced"
    assert curiosity.card_level(card("discord-webrtc-voice")) == "intermediate"
    levels = {item["level"] for item in curiosity.build_curiosity_cards(None, limit=curiosity.MAX_CURIOSITY_CARDS)}
    assert levels == set(curiosity.LEVELS)


def test_strong_fresh_cards_are_saved_and_return_after_the_archive_forgets_them(monkeypatch, tmp_path):
    from app import server, web_digest
    store = Store(f"sqlite:///{(tmp_path / 'library.sqlite').as_posix()}")
    recent = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    deep = {"id": "deep-story", "source_id": "engineering-discord", "source": "engineering-discord", "publisher": "Discord Blog",
            "title": "How we cut p99 latency by 80% across 4,000 Kafka partitions",
            "url": "https://discord.com/blog/p99-latency-kafka-partitions", "published_at": recent,
            "kind": "engineering", "category": "software",
            "description": ("Engineers explain the distributed architecture, replication and caching changes that cut "
                            "tail latency by 80 percent for 4,000 Kafka partitions, with profiling data. ") * 2}
    rows = [deep]
    monkeypatch.setattr(store, "curiosity_candidates", lambda source_ids, **kwargs: rows)
    monkeypatch.setattr(web_digest, "build_digest", lambda articles, *args, **kwargs: {"articles": [
        {"digest_id": item["id"], "summary": item["description"], "summary_basis": "ai_feed_summary",
         "whyItMatters": "Shows how tail latency was measured and reduced."} for item in articles]})
    assert curiosity.quality_score(deep) >= curiosity.KEEP_SCORE
    first = {card["id"]: card for card in curiosity.build_curiosity_cards(store, limit=curiosity.MAX_CURIOSITY_CARDS)}
    assert not first["deep-story"]["seed"]

    rows.clear()  # The article aged out of the 90-day archive.
    later = {card["id"]: card for card in curiosity.build_curiosity_cards(store, limit=curiosity.MAX_CURIOSITY_CARDS)}
    saved = later["deep-story"]
    assert saved["seed"] and saved["archived"] and saved["url"] == deep["url"]
    assert saved["why_read"] == "Shows how tail latency was measured and reduced."
    assert len([card for card in later.values() if card["id"] == "deep-story"]) == 1

    # A saved card can still be added to a brief and scheduled email.
    from app.curiosity import resolve_curiosity_cards
    assert resolve_curiosity_cards(store, ["deep-story"])[0]["url"] == deep["url"]
    captured = {}
    monkeypatch.setattr(server, "select_candidates", lambda pool, focus, count, sources: [])
    monkeypatch.setattr(server, "build_digest", lambda articles, *a, **k: captured.setdefault("articles", articles) and {"articles": []})
    server.prepare_digest(server.DigestRequest(pinned_ids=["deep-story"]), store, "Reader", "", False, None)
    assert [item["url"] for item in captured["articles"]] == [deep["url"]]


def test_library_keeps_only_the_best_cards(tmp_path):
    store = Store(f"sqlite:///{(tmp_path / 'library-trim.sqlite').as_posix()}")
    cards = [({"id": f"card-{index}", "title": f"Story {index}", "url": f"https://example.test/{index}"}, index)
             for index in range(12)]
    store.keep_curiosity_cards(cards, limit=5)
    kept = store.curiosity_library(50)
    assert [card["id"] for card in kept] == ["card-11", "card-10", "card-9", "card-8", "card-7"]
