"""Grouped coverage facts: first publisher, lead time, publisher count and regions."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest

from app import event_intelligence, story_groups
from app.launch_store import get_store
from app.sources import BY_ID

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)


def test_summary_counts_publisher_groups_once_and_names_the_first():
    summary = story_groups.coverage_summary([
        {"source_id": "the-verge", "publisher": "The Verge", "published_at": (NOW + timedelta(minutes=40)).isoformat()},
        {"source_id": "techcrunch", "publisher": "TechCrunch", "published_at": NOW.isoformat()},
        {"source_id": "techcrunch", "publisher": "TechCrunch", "published_at": (NOW + timedelta(hours=3)).isoformat()},
        {"source_id": "sifted", "publisher": "Sifted", "published_at": (NOW + timedelta(hours=2)).isoformat()},
        {"source_id": "techcabal", "publisher": "TechCabal", "published_at": "not a date"},
    ])
    assert summary["publishers"] == 4
    assert summary["first_reported_by"] == "TechCrunch" and summary["lead_minutes"] == 40
    assert summary["names"][:3] == ["TechCrunch", "The Verge", "Sifted"]
    assert {region["id"]: region["count"] for region in summary["regions"]} == {"Global": 2, "EU": 1, "Africa": 1}
    assert summary["regions"][0]["label"] == "Global publishers"
    assert story_groups.coverage_summary([]) is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'groups.sqlite'}")
    monkeypatch.delenv("VERCEL", raising=False)
    store = get_store()
    store.migrate()
    from app import server
    server._news_cache.clear()
    yield TestClient(server.app), store
    server._news_cache.clear()


def add(store, ident, feed, title, moment):
    source = BY_ID[feed]
    row = {"id": ident, "source": source.group, "source_id": feed, "publisher": source.label, "kind": source.kind,
           "category": source.topic or "software", "url": f"https://{source.hosts[0]}/{ident}", "published_at": moment.isoformat(),
           "title": title, "description": title}
    store.ingest(feed, [row], True)
    event_intelligence.observe(store, row)
    return row


def test_reading_room_stories_carry_grouped_coverage_and_development_pages_summarise_it(client):
    http, store = client
    start = datetime.now(UTC) - timedelta(hours=5)
    title = "CrowdStrike agrees to acquire Zscaler for $43.9 billion in record security deal"
    add(store, "g-1", "techcrunch", title, start)
    add(store, "g-2", "the-verge", title, start + timedelta(minutes=25))
    add(store, "g-3", "sifted", title, start + timedelta(hours=1))
    add(store, "solo", "wired", "A calm review of desk lamps for home offices", start)
    stories = {story["id"]: story for story in http.get("/api/news", params={"hours": 24, "limit": 24}).json()["articles"]}
    grouped = stories["g-2"]
    assert grouped["coverage_count"] == 3 and grouped["development_id"]
    summary = grouped["coverage_summary"]
    assert summary["first_reported_by"] == BY_ID["techcrunch"].label and summary["lead_minutes"] == 25
    assert {region["id"] for region in summary["regions"]} == {"Global", "EU"}
    assert "coverage_summary" not in stories["solo"] and "development_id" not in stories["solo"]
    development = http.get(f"/api/intelligence/events/{grouped['development_id']}").json()
    assert development["coverage_summary"]["publishers"] == 3


def test_annotation_survives_missing_event_tables(client, monkeypatch):
    _, store = client
    monkeypatch.setattr(event_intelligence, "ready", lambda store: False)
    rows = [{"id": "x", "title": "t"}]
    assert story_groups.annotate_articles(store, rows) == [{"id": "x", "title": "t"}]
