"""The daily site health workflow is read-only and separate from the feed schedule."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_site_health_workflow_is_read_only_and_checks_the_new_surfaces():
    text = (ROOT / ".github/workflows/site-health.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text
    assert "secrets." not in text and "--request" not in text and "-X " not in text
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
