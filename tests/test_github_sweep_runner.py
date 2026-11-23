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
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(204)

    monkeypatch.setattr(server.httpx, "post", post)
    daily_clock(MORNING + timedelta(minutes=1))
    result = client.post(VERCEL_SWEEP, headers=HEADERS).json()
    assert result == {"status": "dispatched", "runner": "github", "scheduled_at": MORNING.isoformat()}
    url, kwargs = calls[0]
    assert url == ("https://api.github.com/repos/harshgavandit/AI_News_To_Email_Generator"
                   "/actions/workflows/refresh-feeds.yml/dispatches")
    assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert kwargs["json"] == {"ref": "main", "inputs": {"feeds_only": "true"}}


@pytest.mark.parametrize("reply", [httpx.Response(403), httpx.ConnectError("down")])
def test_vercel_sweeps_itself_when_github_refuses(archive, monkeypatch, daily_clock, reply):  # noqa: F811
    store, client = archive
    monkeypatch.setenv("GITHUB_SWEEP_TOKEN", TOKEN)
    sources = tuple(source for source in ingestion.DEFAULT_SOURCES if source.enabled)[:2]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", sources)
    monkeypatch.setattr(ingestion, "read_feed", lambda feed, **kwargs: ([], {"available": True}))

    def post(url, **kwargs):
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(server.httpx, "post", post)
    daily_clock(MORNING + timedelta(minutes=1))
    result = client.post(VERCEL_SWEEP, headers=HEADERS).json()
    assert result["status"] == "refreshed" and result["checked"] == 2


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


def test_workflow_runs_the_sweep_in_the_runner_not_on_vercel():
    workflow = (ROOT / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8")
    refresh_job = workflow.split("  refresh:\n", 1)[1].split("  mail:\n", 1)[0]
    priority_job = workflow.split("  priority:\n", 1)[1]
    for job in (refresh_job, priority_job):
        assert "/api/jobs/refresh" not in job and "curl" not in job
        assert "NEWS_DATABASE_URL: ${{ secrets.NEWS_DATABASE_URL }}" in job
        assert "persist-credentials: false" in job and "uv sync --frozen" in job
    assert "inputs.run != 'priority'" in refresh_job
