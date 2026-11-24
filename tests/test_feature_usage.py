"""Anonymous feature usage counts for "Ask about this story"."""
from fastapi.testclient import TestClient
import pytest

from app import feature_usage
from app.launch_store import Store, get_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'usage.sqlite'}")
    monkeypatch.delenv("VERCEL", raising=False)
    store = get_store()
    store.migrate()
    from app import server
    server._limits.clear()
    yield TestClient(server.app), store


def test_known_events_become_daily_totals_and_unknown_ones_are_ignored(client):
    http, store = client
    events = [{"feature": "story_dossier", "action": "open"}] * 3 + [
        {"feature": "story_ask", "action": "open"}, {"feature": "story_ask", "action": "question"},
        {"feature": "story_ask", "action": "answered"}, {"feature": "story_ask", "action": "stolen-data"}]
    assert http.post("/api/usage/events", json={"events": events}).status_code == 204
    assert http.post("/api/usage/events", json={"events": [{"feature": "story_ask", "action": "question"}]}).status_code == 204
    assert feature_usage.totals(store, "2000-01-01") == {("story_dossier", "open"): 3, ("story_ask", "open"): 1,
                                                          ("story_ask", "question"): 2, ("story_ask", "answered"): 1}
    columns = {column.name for column in feature_usage.feature_usage.columns}
    assert columns == {"day", "feature", "action", "count"}  # nothing about the reader, story or question


def test_privacy_signals_unknown_features_and_oversized_batches(client):
    http, store = client
    event = {"events": [{"feature": "story_ask", "action": "question"}]}
    assert http.post("/api/usage/events", json=event, headers={"Sec-GPC": "1"}).status_code == 204
    assert http.post("/api/usage/events", json=event, headers={"DNT": "1"}).status_code == 204
    assert feature_usage.totals(store, "2000-01-01") == {}
    assert http.post("/api/usage/events", json={"events": [{"feature": "admin", "action": "open"}]}).status_code == 422
    assert http.post("/api/usage/events", json={"events": [{"feature": "story_ask", "action": "open"}] * 21}).status_code == 422
    assert http.post("/api/usage/events", json={"events": [], "question": "secret"}).status_code == 422


def test_monthly_report_shows_ask_rates(client):
    from scripts import curiosity_upkeep
    _, store = client
    assert "No counts in the last 35 days" in curiosity_upkeep.feature_usage_section(35, lambda: store)
    events = ([feature_usage.UsageEvent(feature="story_dossier", action="open")] * 40
              + [feature_usage.UsageEvent(feature="story_ask", action="open")] * 6
              + [feature_usage.UsageEvent(feature="story_ask", action="question")] * 4
              + [feature_usage.UsageEvent(feature="story_ask", action="answered")] * 3
              + [feature_usage.UsageEvent(feature="story_ask", action="unanswered")])
    feature_usage.record(store, events)
    section = curiosity_upkeep.feature_usage_section(35, lambda: store)
    assert "- Story details opened: 40" in section and "Questions asked: 4 (10% of story details)" in section
    assert "Answered with sources: 3 (75% of questions)" in section


def test_counts_work_on_both_databases(research_database):
    store = Store(research_database)
    store.migrate()
    event = feature_usage.UsageEvent(feature="story_ask", action="question")
    feature_usage.record(store, [event, event], day="2026-11-24")
    feature_usage.record(store, [event], day="2026-11-24")
    assert feature_usage.totals(store, "2026-11-01") == {("story_ask", "question"): 3}
    store.engine.dispose()
