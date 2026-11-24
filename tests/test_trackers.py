"""Trackers: model launches, incidents, CVEs and releases detected from stored articles."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest

from app import trackers
from app.launch_store import get_store
from app.sources import BY_ID


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'trackers.sqlite'}")
    monkeypatch.delenv("VERCEL", raising=False)
    store = get_store()
    store.migrate()
    trackers._tracker_cache.clear()
    from app.server import app
    yield TestClient(app), store
    trackers._tracker_cache.clear()


def add(store, ident, feed, title, excerpt="", *, path=None, hours_ago=1):
    source = BY_ID[feed]
    row = {"id": ident, "source": source.group, "source_id": feed, "publisher": source.label, "kind": source.kind,
           "category": source.topic or "software", "url": f"https://{source.hosts[0]}{path or '/' + ident}",
           "published_at": (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(), "title": title,
           "description": excerpt or title}
    store.ingest(feed, [row], True)
    return row


@pytest.mark.parametrize("title,official,names", [
    ("Introducing Gemini 4 Neon", True, ["Gemini 4", "Gemini 4 Neon"]),
    ("Welcome Inkling 2 Mini, cutting-edge performance for your local setup", True, ["Inkling 2 Mini"]),
    ("DaisyRose-27B: Pushing the frontier of post-training efficiency", True, ["DaisyRose-27B"]),
    ("Hebbia sees improvements in financial research with GPT-6 Astra", True, []),
    ("Anthropic announces closing of initial public offering", True, []),
    ("Z AI Releases GLM-5.4: A 750B Loop Transformer That Runs 28 Layers Twice", False, ["GLM-5.4"]),
    ("Acme releases Falcon 3 open-weight models", False, ["Falcon 3"]),
    ("Windows 11 rolls out new AI features", False, []),
    ("Baseten Releases Bison-1 Model for agents", False, ["Bison-1"]),
    ("Ignite 2026: Microsoft launches agents", False, []),
])
def test_model_names_are_launches_not_mentions(title, official, names):
    assert trackers.model_names({"title": title}, official) == names


@pytest.mark.parametrize("title,expected", [
    ("v1.36.0", ("1.36.0", "minor")), ("Release v2.0.0", ("2.0.0", "major")), ("Django 5.2.3", ("5.2.3", "patch")),
    ("Redis 8.4", ("8.4", "minor")), ("v1.20261124.0", ("1.20261124.0", "calendar")), ("2026.11.3", ("2026.11.3", "calendar")),
])
def test_version_levels(title, expected):
    parsed = trackers.parse_version(title)
    assert (parsed["version"], parsed["level"]) == expected
    assert trackers.parse_version("vLLM v0.11.0rc1")["prerelease"] is True
    assert trackers.parse_version("Weekly notes") is None


def test_ai_model_tracker_groups_official_posts_with_reporting(client):
    http, store = client
    add(store, "lab-1", "google-deepmind", "Introducing Gemini 4 Neon", "Our newest model for fast reasoning.", hours_ago=30)
    add(store, "news-1", "the-verge", "Google launches Gemini 4 Neon model for developers", hours_ago=5)
    add(store, "lab-2", "openai-news", "Hebbia sees improvements with GPT-6 Astra")
    data = http.get("/api/trackers/ai-models").json()
    assert data["notice"].startswith("Detected automatically")
    neon = next(item for item in data["items"] if item["name"] == "Gemini 4 Neon")
    assert neon["official"] is True and neon["headline"]["publisher"] == "Google DeepMind"
    assert neon["outlets"] == 2 and len(neon["sources"]) == 2
    assert all("GPT-6" not in item["name"] for item in data["items"])


def test_incident_board_reports_state_per_provider(client):
    http, store = client
    add(store, "cf-1", "cloudflare-status", "Workers API - Delayed responses", "Investigating - We are investigating delays.", hours_ago=1)
    add(store, "cf-0", "cloudflare-status", "Elevated latency in Frankfurt", "Resolved - This incident has been resolved.", hours_ago=20)
    add(store, "gh-1", "github-status", "Incident with Actions", "Resolved - This incident has been resolved.", hours_ago=3)
    board = http.get("/api/trackers/incidents").json()["items"]
    providers = {item["provider"]: item for item in board["providers"]}
    assert providers["Cloudflare"]["open"] is True
    assert [update["state"] for update in providers["Cloudflare"]["updates"]] == ["investigating", "resolved"]
    assert providers["GitHub"]["open"] is False
    assert board["providers"][0]["provider"] == "Cloudflare"  # most recent first


def test_security_tracker_groups_cves_and_flags_exploitation(client):
    http, store = client
    add(store, "kev", "cisa-alerts", "CISA Adds Two Known Exploited Vulnerabilities to Catalog",
        "CVE-2026-1111 Example Router; CVE-2026-2222 Example Mail Server.")
    add(store, "news-cve", "bleepingcomputer", "Hackers exploit Example Router flaw CVE-2026-1111 in attacks")
    add(store, "usn", "ubuntu-security-notices", "USN-9189-1: Qt5Compat vulnerability", "Fixes a flaw in Qt5Compat.")
    add(store, "diary", "ubuntu-security-notices", "Weekly community notes", "Nothing security related.")
    data = http.get("/api/trackers/security").json()["items"]
    first = data["cves"][0]
    assert first["cve"] == "CVE-2026-1111" and first["exploited"] is True and first["outlets"] == 2
    assert {item["cve"] for item in data["cves"]} == {"CVE-2026-1111", "CVE-2026-2222"}
    assert [item["title"] for item in data["advisories"]] == ["USN-9189-1: Qt5Compat vulnerability"]


def test_release_tracker_keeps_latest_stable_release_per_project(client):
    http, store = client
    add(store, "next-old", "release-vercel-next-js", "v16.0.0", path="/vercel/next.js/releases/tag/v16.0.0", hours_ago=48)
    add(store, "next-rc", "release-vercel-next-js", "v16.1.0-canary.3", path="/vercel/next.js/releases/tag/v16.1.0-canary.3", hours_ago=2)
    add(store, "django", "release-django-django", "Django 5.2.3", path="/django/django/releases/tag/5.2.3", hours_ago=5)
    items = http.get("/api/trackers/releases").json()["items"]
    projects = {item["project"]: item for item in items}
    assert projects["vercel/next.js"]["version"] == "16.0.0" and projects["vercel/next.js"]["level"] == "major"
    assert projects["django/django"]["level"] == "patch"


def test_tracker_api_validation_and_caching(client):
    http, _ = client
    assert http.get("/api/trackers/nope").status_code == 404
    assert http.get("/api/trackers/releases", params={"days": 31}).status_code == 422
    response = http.get("/api/trackers/releases", params={"days": 3})
    assert response.json()["days"] == 3 and "s-maxage=300" in response.headers["vercel-cdn-cache-control"]
    assert [item["id"] for item in http.get("/api/trackers").json()["trackers"]] == list(trackers.KINDS)
