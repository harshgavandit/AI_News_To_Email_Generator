"""Regressions for material news lost between ingestion and discovery."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json

from fastapi.testclient import TestClient
import pytest

from app import discovery_health, ingestion
from app.coverage import topic_for
from app.headlines import build_headlines
from app.launch_store import Store
from app.news import article_in_scope
from app.news_signals import impact_score, news_score, story_signals
from app.publisher_listing import read_listing
from app.release_notes import read_release_notes
from app.server import app
from app.sources import BY_ID


def item(ident, title, source_id="bbc-tech", hours=1):
    source = BY_ID[source_id]
    return dict(id=ident, title=title, source_id=source.id, source=source.group, publisher=source.label,
                kind=source.kind, category="News", description="A short publisher excerpt.",
                url=f"https://{source.hosts[0]}/{ident}",
                published_at=(datetime.now(UTC) - timedelta(hours=hours)).isoformat())


@pytest.mark.parametrize(("title", "signal"), [
    ("MongoDB acquires Firebolt", "acquisition"),
    ("Anthropic IPO delays some deals", "ipo"),
    ("Gemini tasks are now free", "launch"),
    ("Linked billing is now in beta on the Claude Platform", "launch"),
    ("Microsoft Ignite 2026 keynote", "launch"),
    ("Microsoft launches AI Transparency Initiative", "policy"),
    ("Kospi gains on Nvidia quarterly results", "earnings"),
    ("Alibaba unveils new flagship Qwen4-Max model", "launch"),
    ("Microsoft explains last week's global outage", "outage"),
])
def test_material_event_signals(title, signal):
    row = item("event", title)
    assert signal in {value["id"] for value in story_signals(row)}
    assert impact_score(row) >= 10


def test_recency_and_commerce_do_not_pin_old_or_shopping_news():
    recent = item("recent", "Nvidia earnings beat expectations")
    assert news_score(recent) > news_score(item("old", recent["title"], hours=70)) > 0
    assert not story_signals(item("offer", "Black Friday best deals launch today"))
    assert news_score(item("bad", "Service outage") | {"published_at": "invalid"}) == 0


@pytest.mark.parametrize("title", [
    "Claude describes a future AI takeover", "Java4Shell puts applications at risk of takeover",
    "A model raises concerns about benchmarks", "A compiler raises a runtime error",
])
def test_ambiguous_takeover_and_raises_are_not_corporate_events(title):
    assert not {"acquisition", "funding"} & {value["id"] for value in story_signals(item("ambiguous", title))}


@pytest.mark.parametrize("title", ["Startup raises $500 million", "Startup raises a new round", "Startup raises €20m"])
def test_funding_signals_keep_explicit_capital_raises(title):
    assert "funding" in {value["id"] for value in story_signals(item("capital", title))}


def test_earnings_not_hidden_by_another_nvidia_development():
    rows = [item("earnings", "Nvidia quarterly earnings surge"),
            item("leadership", "Nvidia CEO search continues", "the-verge", hours=40)]
    result = build_headlines(rows)
    assert result["articles"][0]["id"] == "earnings"
    assert {row["id"] for row in result["articles"]} == {"earnings", "leadership"}
    assert result["coverage"] == []


def test_dynamic_coverage_requires_matching_event_and_distinct_publisher_families():
    title = "MongoDB acquires Firebolt to expand real time analytics"
    rows = [item("one", title), item("two", title, "the-verge"),
            item("three", "MongoDB launches a developer conference", "ars-technica")]
    result = build_headlines(rows)
    assert len(result["coverage"]) == 1
    assert len(result["coverage"][0]["sources"]) == 2
    assert [row["id"] for row in result["articles"]] == ["three"]
    same_family = [item("official", title, "microsoft-official-blog"),
                   item("newsroom", title, "microsoft-source")]
    assert not build_headlines(same_family)["coverage"]


def test_entity_scope_and_official_video_classification():
    financial = BY_ID["cnbc-markets"]
    assert article_in_scope(financial, "/story", "MongoDB acquires Firebolt", [])
    assert not article_in_scope(financial, "/story", "Oil prices rise on weather concerns", [])
    assert topic_for(item("gemini", "Gemini tasks are now free", "9to5google")) == "ai"
    assert topic_for(item("qwen", "Qwen4-Max is now available", "qwen-official")) == "ai"
    assert topic_for(item("video", "Anthropic IPO update", "bloomberg-video")) != "video"
    assert BY_ID["bloomberg-video"].publisher_family != BY_ID["reuters-video"].publisher_family
    assert BY_ID["microsoft-video"].publisher_family == BY_ID["microsoft-source"].publisher_family


def test_candidate_sampling_keeps_important_older_news(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'candidates.db'}")
    rows = [item(f"routine-{i}", f"A routine software update number {i}") for i in range(40)]
    rows.append(item("earnings", "Nvidia quarterly earnings surge", hours=20))
    store.ingest("bbc-tech", rows, True)
    assert "earnings" in {row["id"] for row in store.headline_candidates(24, per_source=10)}
    assert "earnings" in {row["id"] for row in store.world_candidates(24, ["bbc-tech"])}
    page = store.page(hours=24, source="all", query="earnings", kind="all", publisher="", limit=5, cursor=None)
    assert page["total"] == 1


def test_significant_official_release_notes_reach_headlines_and_daily_brief(tmp_path):
    from app.briefing import build_briefing
    from app.signals import priority_signals
    store = Store(f"sqlite:///{tmp_path / 'release.db'}")
    rows = [item("billing", "Linked billing is now in beta", "claude-platform-notes"),
            item("patch", "SDK version 1.2.3", "claude-platform-notes")]
    store.ingest("claude-platform-notes", rows, True)
    candidates = store.headline_candidates(24, include_primary=True)
    assert [row["id"] for row in candidates] == ["billing"]
    assert [row["id"] for row in build_headlines(rows)["articles"]] == ["billing"]
    assert [row["id"] for row in build_briefing(rows)["articles"]] == ["billing"]
    assert [row["id"] for row in priority_signals(rows)["articles"]] == ["billing"]


def test_official_changelog_has_stable_ids_real_dates_and_short_excerpts():
    source = BY_ID["claude-platform-notes"]
    date = datetime.now(UTC).strftime("%B %d, %Y")
    body = (f"# Updates\n## {date}\n* Linked billing is now in beta. [Read more](https://example.com/docs).\n"
            "* Another technical release.\n## January 1, 2020\n* An expired release.\n").encode()
    rows, status = read_release_notes(source, lambda _: body)
    assert status["available"] and len(rows) == 2
    assert rows[0]["id"] != rows[1]["id"]
    assert rows == read_release_notes(source, lambda _: body)[0]
    assert rows[0]["publication_date_precision"] == "day"
    assert rows[0]["published_at"].endswith("T00:00:00+00:00")
    assert "Linked billing" in rows[0]["title"] and "https://example" not in rows[0]["description"]
    assert rows[0]["url"].startswith(source.url.removesuffix(".md") + "#")
    with pytest.raises(ValueError):
        read_release_notes(source, lambda _: b"<html>No changelog here</html>")


def test_extensionless_listing_continues_past_known_frontpage_articles():
    source = BY_ID["ctech-news"]
    links = [f"https://www.calcalistech.com/ctechnews/article/story-{i}" for i in range(12)]
    fetched = []

    def fetch(url):
        fetched.append(url)
        if url.endswith("robots.txt"):
            return b"User-agent: *\nAllow: /\n"
        if url == source.url:
            return "".join(f'<a href="{link}">News</a>' for link in links).encode()
        return ('<script type="application/ld+json">' + json.dumps({"@type": "NewsArticle",
            "headline": "MongoDB acquires a software startup", "datePublished": datetime.now(UTC).isoformat(),
            "description": "Publisher metadata.", "articleBody": "Do not copy the article body."}) + '</script>').encode()

    rows, state = read_listing(source, fetch, known_urls=set(links[:9]))
    assert state["available"] and len(rows) == 3
    assert not set(links[:9]) & set(fetched)
    assert "Do not copy" not in str(rows)


def test_refresh_urgency_preserves_old_source_fairness_and_backoff(monkeypatch):
    now = datetime.now(UTC).timestamp()
    fast = replace(BY_ID["bbc-tech"], id="fast", refresh_minutes=5)
    slow = replace(BY_ID["techcrunch"], id="slow", refresh_minutes=120)
    oldest = replace(BY_ID["9to5google"], id="oldest", refresh_minutes=1440)
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (fast, slow, oldest))
    state = {fast.id: {"checked": now - 3600}, slow.id: {"checked": now - 7200}, oldest.id: {"checked": now - 100000}}
    assert ingestion.refresh_plan(state, maximum=2, now=now) == [oldest, fast]
    state[fast.id]["retry_at"] = now + 600
    assert fast not in ingestion.refresh_plan(state, now=now)


def test_public_monitor_distinguishes_stalled_ingestion_and_sampled_coverage(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'monitor.db'}")
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (BY_ID["bbc-tech"],))
    monkeypatch.setattr(discovery_health, "get_store", lambda: store)
    client = TestClient(app)
    assert client.get("/api/discovery/ingestion").json()["status"] == "stalled"
    store.ingest("bbc-tech", [item("event", "MongoDB acquires Firebolt")], True)
    result = client.get("/api/discovery/ingestion").json()
    assert result["status"] == "running" and result["due_sources"] == 0
    coverage = client.get("/api/discovery/coverage").json()
    acquisition = next(signal for signal in coverage["signals"] if signal["id"] == "acquisition")
    assert acquisition["sampled_articles"] == 1 and acquisition["publisher_groups"] == 1
    assert next(signal for signal in coverage["signals"] if signal["id"] == "ipo")["gap"] == "no_matching_headlines_in_sample"
