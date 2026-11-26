"""The daily site health workflow is read-only and separate from the feed schedule."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_site_health_workflow_is_read_only_and_checks_the_new_surfaces():
    text = (ROOT / ".github/workflows/site-health.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"SITE_MONITOR_TOKEN"}
    assert "--request" not in text and "-X " not in text and "--location" not in text
    assert "--header @-" in text and 'X-Informa-Site-Monitor: $SITE_MONITOR_TOKEN' in text
    crons = re.findall(r"cron: '([^']+)'", text)
    feed_crons = re.findall(r"cron: '([^']+)'", (ROOT / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8"))
    assert crons and not set(crons) & set(feed_crons)
    for path in ("/api/trackers/releases", "/api/recap", "/feeds/latest.xml", "/api/push/config", "/sw.js"):
        assert path in text


def test_recap_job_workflow_uses_its_own_schedule_and_the_job_secret_only():
    text = (ROOT / ".github/workflows/weekly-recap.yml").read_text(encoding="utf-8")
    feed_crons = re.findall(r"cron: '([^']+)'", (ROOT / ".github/workflows/refresh-feeds.yml").read_text(encoding="utf-8"))
    assert not set(re.findall(r"cron: '([^']+)'", text)) & set(feed_crons)
    assert "/api/jobs/recap" in text and set(re.findall(r"secrets\.(\w+)", text)) == {"FEED_REFRESH_SECRET"}


def test_smoke_token_is_not_forwarded_by_redirects(monkeypatch):
    from urllib.request import HTTPRedirectHandler

    import pytest

    from scripts import check_production_release

    monkeypatch.setenv("SITE_MONITOR_TOKEN", "probe-secret-for-tests")

    def follow_redirect(request, **kwargs):
        assert request.get_header("X-informa-site-monitor") == "probe-secret-for-tests"
        follow = HTTPRedirectHandler().redirect_request(
            request, None, 302, "", {}, "https://example.com/"
        )
        assert not follow.has_header("X-informa-site-monitor")
        raise ValueError("redirect inspected")

    monkeypatch.setattr(check_production_release, "urlopen", follow_redirect)
    with pytest.raises(ValueError, match="redirect inspected"):
        check_production_release.fetch("/api/health", "application/json")
