"""The publisher sweep runs on GitHub Actions; Vercel's schedule only starts it."""
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app import ingestion, server
from scripts import run_publisher_sweep
from tests.test_refresh_reliability import MORNING, VERCEL_SWEEP, archive, daily_clock  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "github_pat_" + "x" * 40
HEADERS = {"Authorization": "Bearer cron-secret-for-tests", "ce-vssscheduledat": MORNING.isoformat()}


def no_fetch(*args, **kwargs):
    raise AssertionError("Vercel must not fetch feeds once the GitHub run has started")


def test_vercel_schedule_starts_the_github_run_instead_of_fetching(archive, monkeypatch, daily_clock):  # noqa: F811
    store, client = archive
    monkeypatch.setenv("GITHUB_SWEEP_TOKEN", TOKEN)
    monkeypatch.setattr(server, "refresh_sources", no_fetch)
    monkeypatch.setattr(server, "VERCEL_FETCHED", frozenset())
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(204)

    monkeypatch.setattr(server.httpx, "post", post)
    daily_clock(MORNING + timedelta(minutes=1))
    result = client.post(VERCEL_SWEEP, headers=HEADERS).json()
    assert {key: result[key] for key in ("status", "runner", "scheduled_at")} == {
        "status": "dispatched", "runner": "github", "scheduled_at": MORNING.isoformat()}
    url, kwargs = calls[0]
    assert url == ("https://api.github.com/repos/harshgavandit/AI_News_To_Email_Generator"
                   "/actions/workflows/refresh-feeds.yml/dispatches")
    assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert kwargs["json"] == {"ref": "main", "inputs": {"feeds_only": "true"}}


@pytest.mark.parametrize("reply", [httpx.Response(403), httpx.ConnectError("down")])
def test_vercel_checks_only_its_publishers_when_github_refuses(archive, monkeypatch, daily_clock, reply):  # noqa: F811
    store, client = archive
    monkeypatch.setenv("GITHUB_SWEEP_TOKEN", TOKEN)
    sources = tuple(source for source in ingestion.DEFAULT_SOURCES if source.enabled)[:2]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", sources)
    monkeypatch.setattr(server, "VERCEL_FETCHED", frozenset({sources[0].id}))
    fetched = []
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: (fetched.append(feed.id) or [], {"available": True}))

    def post(url, **kwargs):
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(server.httpx, "post", post)
    daily_clock(MORNING + timedelta(minutes=1))
    result = client.post(VERCEL_SWEEP, headers=HEADERS).json()
    assert result["status"] == "refreshed" and result["vercel_feeds"]["checked"] == 1
    assert fetched == [sources[0].id]


def test_no_token_and_late_deliveries_never_dispatch(archive, monkeypatch, daily_clock):  # noqa: F811
    store, client = archive
    monkeypatch.setattr(server.httpx, "post", lambda *a, **k: pytest.fail("dispatched without a token"))
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", ())
    daily_clock(MORNING + timedelta(minutes=1))
    assert client.post(VERCEL_SWEEP, headers=HEADERS).json()["status"] != "dispatched"
    monkeypatch.setenv("GITHUB_SWEEP_TOKEN", TOKEN)
    daily_clock(MORNING + ingestion.SWEEP_WINDOW + timedelta(minutes=1))
    assert client.post(VERCEL_SWEEP, headers=HEADERS).json()["status"] == "closed"


def test_runner_finishes_the_whole_sweep_in_one_job(archive, monkeypatch, daily_clock):  # noqa: F811
    store, client = archive
    sources = tuple(source for source in ingestion.DEFAULT_SOURCES if source.enabled)[:6]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", sources)
    fetched = []
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: (fetched.append(feed.id) or [], {"available": True}))
    daily_clock(MORNING + timedelta(minutes=3))
    summary = run_publisher_sweep.sweep("full", 600)
    assert summary["status"] == "refreshed" and summary["checked"] == 6 and summary["remaining"] == 0
    assert sorted(fetched) == sorted(source.id for source in sources)
    assert run_publisher_sweep.sweep("full", 600)["status"] == "complete"
    assert len(fetched) == 6, "each source is checked once per sweep"
    assert run_publisher_sweep.outcome("full", summary) == 0


def test_runner_waits_for_a_held_lease_and_reports_stalls(monkeypatch):
    replies = iter([{"status": "already_started"},
                    {"status": "refreshed", "checked": 3, "healthy": 3, "remaining": 2},
                    {"status": "refreshed", "checked": 2, "healthy": 1, "remaining": 0,
                     "failures": [{"id": "x", "label": "X", "reason": "feed_not_found"}]}])
    monkeypatch.setattr(server, "run_sweep", lambda **kwargs: next(replies))
    slept = []
    summary = run_publisher_sweep.sweep("full", 600, sleep=slept.append)
    assert slept == [30] and summary["checked"] == 5 and summary["healthy"] == 4 and summary["batches"] == 2

    def stalled(**kwargs):
        raise HTTPException(503, "The feed refresh batch made no progress.")

    monkeypatch.setattr(server, "run_sweep", stalled)
    summary = run_publisher_sweep.sweep("full", 600)
    assert summary["status"] == "stalled" and run_publisher_sweep.outcome("full", summary) == 1
    assert run_publisher_sweep.outcome("full", {"status": "closed", "remaining": 4}) == 0
    assert run_publisher_sweep.outcome("full", {"status": "refreshed", "remaining": 4}) == 1
    assert run_publisher_sweep.outcome("priority", {"status": "refreshed", "remaining": 4}) == 0


def test_runner_requires_the_database_secret(monkeypatch, capsys):
    monkeypatch.delenv("NEWS_DATABASE_URL", raising=False)
    assert run_publisher_sweep.main(["--run", "full"]) == 1
    assert "NEWS_DATABASE_URL" in capsys.readouterr().out


def test_feed_only_recovery_never_starts_morning_mail(monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", "sqlite://")
    monkeypatch.setattr(run_publisher_sweep, "wait_for_slot", lambda kind: None)
    monkeypatch.setattr(run_publisher_sweep, "sweep", lambda *args: {"status": "refreshed", "checked": 3})
    monkeypatch.setattr(run_publisher_sweep, "start_morning_mail", lambda *args: pytest.fail("recovery started mail"))
    assert run_publisher_sweep.main(["--run", "full", "--feeds-only"]) == 0


def test_runner_explains_an_unusable_database_without_printing_the_url(monkeypatch, capsys):
    from sqlalchemy.exc import OperationalError

    url = "postgresql://user:secret@db.example/news"
    monkeypatch.setenv("NEWS_DATABASE_URL", url)
    monkeypatch.setattr(run_publisher_sweep, "wait_for_slot", lambda kind: None)

    def quota(kind, budget):
        raise OperationalError("connect", {}, Exception("ERROR:  Your account or project has exceeded the quota."))

    monkeypatch.setattr(run_publisher_sweep, "sweep", quota)
    assert run_publisher_sweep.main(["--run", "full"]) == 1
    out = capsys.readouterr().out
    assert "used up its plan quota" in out and "Vercel's NEWS_DATABASE_URL" in out and "secret@" not in out

    def unreachable(kind, budget):
        raise OperationalError("connect", {}, Exception("Network is unreachable"))

    monkeypatch.setattr(run_publisher_sweep, "sweep", unreachable)
    assert run_publisher_sweep.main(["--run", "priority"]) == 1
    assert "Could not connect" in capsys.readouterr().out


def test_workflow_runs_the_sweep_in_the_runner_not_on_vercel():
    workflow = (ROOT / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    refresh_job = workflow.split("  refresh:\n", 1)[1].split("  mail:\n", 1)[0]
    priority_job = workflow.split("  priority:\n", 1)[1]
    for job in (refresh_job, priority_job):
        assert "/api/jobs/refresh" not in job and "curl" not in job
        assert "NEWS_DATABASE_URL: ${{ secrets.NEWS_DATABASE_URL }}" in job
        assert "persist-credentials: false" in job and "uv sync --frozen" in job
    assert "inputs.run != 'priority'" in refresh_job


def test_a_run_started_minutes_early_waits_for_its_slot():
    from datetime import datetime, timezone
    slept = []
    # Priority slot 02:00 IST is 20:30 UTC; GitHub started the 20:32 cron at 20:27.
    early = datetime(2026, 11, 23, 20, 27, 56, tzinfo=timezone.utc)
    waited = run_publisher_sweep.wait_for_slot("priority", early, sleep=slept.append)
    assert 120 < waited < 130 and slept == [waited + 5]
    # Full sweep 08:00 IST is 02:30 UTC.
    assert run_publisher_sweep.wait_for_slot("full", datetime(2026, 11, 24, 2, 22, tzinfo=timezone.utc),
                                             sleep=slept.append) == 480
    # Inside a window, or long before the next one, nothing waits.
    slept.clear()
    assert run_publisher_sweep.wait_for_slot("full", datetime(2026, 11, 24, 2, 40, tzinfo=timezone.utc), sleep=slept.append) == 0
    assert run_publisher_sweep.wait_for_slot("priority", datetime(2026, 11, 23, 18, 0, tzinfo=timezone.utc), sleep=slept.append) == 0
    assert slept == []


def test_publishers_that_refuse_github_are_swept_by_vercel_only(archive, monkeypatch, daily_clock):  # noqa: F811
    """GitHub sweeps everything except VERCEL_FETCHED; Vercel's scheduled call fetches just those."""
    store, client = archive
    from app.sources import BY_ID
    blocked, normal = BY_ID["import-ai"], BY_ID["bbc-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (blocked, normal))
    monkeypatch.setattr(server, "BY_ID", {blocked.id: blocked, normal.id: normal})
    fetched = []
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: (fetched.append(feed.id) or [], {"available": True}))
    monkeypatch.setattr(server.httpx, "post", lambda url, **kwargs: httpx.Response(204))
    monkeypatch.setattr(server, "deliver_after_sweep", lambda result: pytest.fail("a partial sweep must not start mail"))
    # The GitHub runner sweeps everything except the Vercel-only feed and still finishes.
    monkeypatch.setenv("INFORMA_SWEEP_RUNNER", "github")
    daily_clock(MORNING + timedelta(minutes=2))
    summary = run_publisher_sweep.sweep("full", 600)
    assert summary["status"] == "refreshed" and summary["remaining"] == 0 and summary["checked"] == 1
    assert fetched == ["bbc-tech"]
    # Vercel's scheduled call starts GitHub and fetches only the feed GitHub cannot reach.
    monkeypatch.delenv("INFORMA_SWEEP_RUNNER")
    monkeypatch.setenv("GITHUB_SWEEP_TOKEN", TOKEN)
    daily_clock(MORNING + timedelta(minutes=5))
    result = client.post(VERCEL_SWEEP, headers=HEADERS).json()
    assert result["status"] == "dispatched" and result["vercel_feeds"]["checked"] == 1
    assert fetched == ["bbc-tech", "import-ai"]


def test_vercel_fetched_sources_exist_and_only_github_excludes_them():
    from app.sources import BY_ID
    assert ingestion.VERCEL_FETCHED <= set(BY_ID)
    assert ingestion.runner_excluded({"INFORMA_SWEEP_RUNNER": "github"}) == ingestion.VERCEL_FETCHED
    assert ingestion.runner_excluded({}) == frozenset()
    workflow = (ROOT / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    for job in ("  refresh:\n", "  priority:\n"):
        section = workflow.split(job, 1)[1].split("\n  mail:\n", 1)[0]
        assert "INFORMA_SWEEP_RUNNER: github" in section

