"""Weekly recap: ISO weeks, ranking by publishers, saved snapshots, API, RSS and the Monday email block."""
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

from fastapi.testclient import TestClient
import pytest

from app import event_intelligence, feeds, weekly_recap
from app.launch_store import get_store
from app.sources import BY_ID


def test_week_ids_and_bounds():
    assert weekly_recap.week_id(datetime(2026, 11, 24, tzinfo=UTC)) == "2026-W48"
    start, end = weekly_recap.week_bounds("2026-W47")
    assert (start, end) == (datetime(2026, 11, 16, tzinfo=UTC), datetime(2026, 11, 23, tzinfo=UTC))
    assert weekly_recap.last_complete_week(datetime(2026, 11, 24, 9, tzinfo=UTC)) == "2026-W47"
    assert weekly_recap.last_complete_week(datetime(2026, 11, 23, 0, 30, tzinfo=UTC)) == "2026-W47"
    assert weekly_recap.week_bounds("2026-W01")[0] == datetime(2025, 12, 29, tzinfo=UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'recap.sqlite'}")
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://getinformdaily.com")
    monkeypatch.delenv("VERCEL", raising=False)
    store = get_store()
    store.migrate()
    feeds._feed_cache.clear()
    from app.server import app
    yield TestClient(app), store
    feeds._feed_cache.clear()


def last_week():
    ident = weekly_recap.last_complete_week()
    return ident, weekly_recap.week_bounds(ident)[0]


def add(store, ident, feed, title, moment, excerpt=""):
    source = BY_ID[feed]
    row = {"id": ident, "source": source.group, "source_id": feed, "publisher": source.label, "kind": source.kind,
           "category": source.topic or "software", "url": f"https://{source.hosts[0]}/{ident}", "published_at": moment.isoformat(),
           "title": title, "description": excerpt or title}
    store.ingest(feed, [row], True)
    event_intelligence.observe(store, row)
    return row


def seed(store, start):
    day = start + timedelta(days=2, hours=9)
    add(store, "big-1", "techcrunch", "CrowdStrike agrees to acquire Zscaler for $43.9 billion in record security deal", day)
    add(store, "big-2", "the-verge", "CrowdStrike agrees to acquire Zscaler for $43.9 billion in record security deal",
        day + timedelta(hours=1))
    add(store, "big-3", "ars-technica", "CrowdStrike agrees to acquire Zscaler for $43.9 billion in a record security deal",
        day + timedelta(hours=2))
    add(store, "small", "wired", "A quiet update to a niche text editor plugin", day + timedelta(hours=3))
    for index, subject in enumerate(("Nvidia ships its Rubin Ultra accelerator to cloud providers",
                                     "Cloudflare outage takes down websites across Europe for two hours",
                                     "European Commission fines Apple over App Store payment rules",
                                     "Microsoft patches Windows zero-day exploited by ransomware gangs")):
        for offset, feed in enumerate(("techcrunch", "the-verge")):
            add(store, f"group-{index}-{offset}", feed, subject, day + timedelta(hours=4 + index, minutes=offset))
    add(store, "older", "techcrunch", "Last month's chip story about wafer yields", start - timedelta(days=3))


def test_recap_ranks_stories_by_publishers_that_week_and_saves_a_snapshot(client):
    http, store = client
    ident, start = last_week()
    seed(store, start)
    assert http.get("/api/recap").status_code == 404  # requests never build; the recap job does
    assert weekly_recap.prepare(store) == "ready"
    data = http.get("/api/recap").json()
    assert data["week"] == ident and data["title"].startswith("This week in tech: ") and data["complete"] is True
    first = data["top_stories"][0]
    assert "Zscaler" in first["title"] and first["outlets"] == 3 and first["first_publisher"] == BY_ID["techcrunch"].label
    assert first["url"].startswith("/development.html?id=")
    titles = [story["title"] for story in data["top_stories"]]
    assert not any("wafer" in title for title in titles)  # published before the week
    assert data["weeks"] == [{"week": ident, "title": data["title"]}]
    add(store, "late", "wired", "CrowdStrike Zscaler deal draws antitrust questions", start + timedelta(days=3))
    assert weekly_recap.prepare(store) == "current"
    assert http.get("/api/recap").json()["generated_at"] == data["generated_at"]  # a complete snapshot is kept
    assert http.get(f"/api/recap/{ident}").json()["week"] == ident


def test_recap_api_rejects_future_unknown_and_malformed_weeks(client):
    http, _ = client
    current = weekly_recap.week_id(datetime.now(UTC))
    assert http.get(f"/api/recap/{current}").status_code == 404  # not finished yet
    assert http.get("/api/recap/2019-W10").status_code == 404  # too old to build
    assert http.get("/api/recap/2026-W99").status_code == 422
    assert http.get("/api/recap/latest").status_code == 422


def test_recap_feed_lists_saved_weeks(client):
    http, store = client
    ident, start = last_week()
    seed(store, start)
    weekly_recap.prepare(store)
    response = http.get("/feeds/recap.xml")
    items = ElementTree.fromstring(response.content).find("channel").findall("item")
    assert items[0].findtext("link") == f"https://getinformdaily.com/recap.html?week={ident}"
    assert "Zscaler" in items[0].findtext("description")


def test_monday_brief_gets_last_weeks_top_stories(client):
    from app.mail_schedule import weekly_recap_for
    _, store = client
    ident, start = last_week()
    seed(store, start)
    weekly_recap.prepare(store)
    monday = weekly_recap.week_bounds(weekly_recap.week_id(datetime.now(UTC)))[0] + timedelta(hours=3)
    tuesday = monday + timedelta(days=1)
    payload = weekly_recap_for(store, monday, "UTC")
    assert payload["week"] == ident
    assert weekly_recap_for(store, tuesday, "UTC") is None
    brief = weekly_recap.append_to_brief({"markdown": "# Brief", "html": "<html><body><p>Brief</p></body></html>"},
                                         payload, "https://getinformdaily.com")
    assert "Last week in tech" in brief["html"] and brief["html"].endswith("</body></html>")
    assert f"https://getinformdaily.com/recap.html?week={ident}" in brief["markdown"]
    empty = {"markdown": "x", "html": "<body></body>"}
    assert weekly_recap.append_to_brief(empty, None, "https://x") is empty


def test_email_block_escapes_headlines():
    payload = {"week": "2026-W47", "stats": {"models": 1, "exploited": 0, "releases": 2},
               "top_stories": [{"title": "<img src=x onerror=alert(1)> wins", "url": "/development.html?id=" + "a" * 32,
                                "topic_label": "AI & Machine Learning", "outlets": 4}]}
    html, _ = weekly_recap.email_block(payload, "https://getinformdaily.com")
    assert "<img" not in html and "&lt;img" in html


def test_recap_snapshots_work_on_both_databases(research_database):
    from app.launch_store import Store
    store = Store(research_database)
    store.migrate()
    weekly_recap.save(store, "2026-W40", {"week": "2026-W40", "title": "empty", "top_stories": []})
    assert weekly_recap.load(store, "2026-W40") is None and weekly_recap.available(store) == []  # empty snapshots are rebuilt
    story = [{"id": "x", "title": "A story"}]
    weekly_recap.save(store, "2026-W40", {"week": "2026-W40", "title": "This week in tech: Sep 28 – Oct 4, 2026", "top_stories": story})
    weekly_recap.save(store, "2026-W40", {"week": "2026-W40", "title": "ignored duplicate", "top_stories": story})
    assert weekly_recap.load(store, "2026-W40")["title"].startswith("This week in tech")
    assert weekly_recap.available(store) == [{"week": "2026-W40", "title": "This week in tech: Sep 28 – Oct 4, 2026"}]
    store.engine.dispose()


def test_thin_weeks_fall_back_to_signal_headlines_and_are_not_frozen(client):
    http, store = client
    ident, start = last_week()
    day = start + timedelta(days=1)
    add(store, "solo-1", "techcrunch", "Startup raises $40 million Series B for robot arms", day)
    add(store, "solo-2", "the-verge", "A calm review of desk lamps", day)
    assert weekly_recap.prepare(store) == "partial"
    data = http.get("/api/recap").json()
    assert data["complete"] is False and data["weeks"] == [{"week": ident, "title": data["title"]}]
    assert data["top_stories"][0]["title"] == "Startup raises $40 million Series B for robot arms"
    assert data["top_stories"][0]["url"].startswith("https://techcrunch.com/")
    assert weekly_recap.prepare(store) == "partial"  # not rebuilt again within six hours
    with store.engine.begin() as conn:
        conn.execute(weekly_recap.weekly_recaps.update().values(created=0))
    seed(store, start)
    assert weekly_recap.prepare(store) == "ready"  # a partial week is replaced once coverage is grouped
    assert http.get("/api/recap").json()["complete"] is True


def test_recap_job_requires_the_job_secret(client, monkeypatch):
    http, store = client
    assert http.get("/api/jobs/recap").status_code == 401
    monkeypatch.setenv("FEED_REFRESH_SECRET", "job-secret-for-tests-123456")
    result = http.get("/api/jobs/recap", headers={"Authorization": "Bearer job-secret-for-tests-123456"}).json()
    assert result["recap_status"] == "unavailable" and result["week"] == weekly_recap.last_complete_week()
