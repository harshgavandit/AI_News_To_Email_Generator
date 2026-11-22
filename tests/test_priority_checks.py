"""Light 02:00/14:00 IST checks of the busiest sources between the two full sweeps."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import ingestion
from app.ingestion import PRIORITY_SOURCE_IDS, PRIORITY_WINDOW, latest_priority_check
from tests.test_refresh_reliability import JOB_HEADERS, MORNING, SWEEP, archive, daily_clock  # noqa: F401

PRIORITY = "/api/jobs/refresh?run=priority"
NIGHT = MORNING - timedelta(hours=6)  # 02:00 IST
ROOT = Path(__file__).resolve().parents[1]


def test_priority_set_is_the_busy_newsrooms_advisories_and_status_pages():
    enabled = [source for source in ingestion.DEFAULT_SOURCES if source.enabled]
    chosen = [source for source in enabled if source.id in PRIORITY_SOURCE_IDS]
    assert {"techcrunch", "the-verge", "bleepingcomputer", "cisa-alerts"} <= PRIORITY_SOURCE_IDS
    assert all(source.coverage in {"reporting", "advisory", "status"} for source in chosen)
    assert all(source.kind != "video" for source in chosen)
    # A light run, not a third and fourth full sweep.
    assert 0 < len(chosen) < len(enabled) * 0.4


def test_priority_slots_are_two_and_fourteen_ist():
    assert latest_priority_check(NIGHT) == NIGHT
    assert NIGHT.astimezone(ingestion.INDIA_TIME).hour == 2
    afternoon = NIGHT + timedelta(hours=12)
    assert afternoon.astimezone(ingestion.INDIA_TIME).hour == 14
    assert latest_priority_check(afternoon + timedelta(minutes=5)) == afternoon
    assert latest_priority_check(afternoon - timedelta(minutes=1)) == NIGHT


def test_priority_run_checks_only_busy_sources_once_and_full_sweep_still_covers_everything(
        archive, monkeypatch, daily_clock):
    _, client = archive
    attempts = []
    monkeypatch.setattr(ingestion, "read_feed", lambda source, **kwargs: (attempts.append(source.id) or [], {"available": True}))
    enabled = {source.id for source in ingestion.DEFAULT_SOURCES if source.enabled}
    busy = enabled & PRIORITY_SOURCE_IDS

    daily_clock(NIGHT - timedelta(minutes=1))
    assert client.get(PRIORITY, headers=JOB_HEADERS).json()["status"] == "closed"
    assert client.get(SWEEP, headers=JOB_HEADERS).json()["status"] == "closed"
    assert client.get(PRIORITY).status_code == 401
    assert not attempts

    daily_clock(NIGHT + timedelta(minutes=10))
    for _ in range(20):
        result = client.get(PRIORITY, headers=JOB_HEADERS).json()
        if result["remaining"] == 0:
            break
    assert result["status"] in {"refreshed", "complete"}
    assert set(attempts) == busy and len(attempts) == len(busy)
    again = client.get(PRIORITY, headers=JOB_HEADERS).json()
    assert (again["status"], again["checked"], again["remaining"]) == ("complete", 0, 0)
    assert len(attempts) == len(busy)

    # The full sweep is unaffected: priority checks happened before it opened.
    daily_clock(NIGHT + PRIORITY_WINDOW)
    assert client.get(PRIORITY, headers=JOB_HEADERS).json()["status"] == "closed"
    attempts.clear()
    daily_clock(MORNING)
    for _ in range(40):
        result = client.get(SWEEP, headers=JOB_HEADERS).json()
        if result["remaining"] == 0:
            break
    assert set(attempts) == enabled


def test_catalog_describes_four_daily_checks_for_priority_sources(archive, daily_clock):
    _, client = archive
    daily_clock(MORNING + timedelta(hours=1))  # 09:00 IST: next light check is 14:00 IST
    feeds = {feed["id"]: feed for feed in ingestion.source_catalog(archive[0])}
    assert feeds["techcrunch"]["refresh_policy"] == "four_times_daily"
    assert feeds["techcrunch"]["next_check_at"] == (MORNING + timedelta(hours=6)).isoformat()
    quiet = next(feed for feed in feeds.values() if feed["enabled"] and feed["id"] not in PRIORITY_SOURCE_IDS)
    assert quiet["refresh_policy"] == "twice_daily"
    assert quiet["next_check_at"] == (MORNING + timedelta(hours=12)).isoformat()


def test_github_starts_priority_runs_inside_their_window_and_vercel_schedule_is_unchanged():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["schedules"]["publisher-feed-sweep"]["schedule"] == "0 8,20 * * *"
    workflow = (ROOT / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    assert "- cron: '32 8,20 * * *'" in workflow
    for hour in (8, 20):
        fired = datetime(2026, 11, 21, hour, 32, tzinfo=UTC)
        opened = latest_priority_check(fired)
        assert timedelta(0) < fired - opened < PRIORITY_WINDOW - timedelta(minutes=60)
    job = workflow.split("  priority:\n", 1)[1]
    assert "if: github.event.schedule == '32 8,20 * * *'" in job
    assert "run=priority" in job and "run=scheduled" not in job
