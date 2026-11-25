"""Reader feedback: validation, spam trap, owner-only reading, retention and count-only summaries."""
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from app import feedback
from app.launch_store import get_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'feedback.sqlite'}")
    monkeypatch.delenv("VERCEL", raising=False)
    store = get_store()
    store.migrate()
    from app import server
    server._limits.clear()
    monkeypatch.setattr(server, "owner_secret", lambda: "owner-key-for-tests-1234567890")
    yield TestClient(server.app, base_url="https://testserver"), store


def owner(http, **params):
    return http.get("/api/admin/feedback", params=params, headers={"Authorization": "Bearer owner-key-for-tests-1234567890"})


def test_feedback_is_stored_and_only_the_owner_can_read_it(client):
    http, _ = client
    sent = http.post("/api/feedback", json={"kind": "bug", "message": "The recap page \x07shows nothing on Safari.",
                                            "page": "/recap.html?week=2026-W47#top", "contact": "reader@example.com"})
    assert sent.status_code == 204
    assert http.post("/api/feedback", json={"kind": "useful", "page": "/trackers.html"}).status_code == 204
    assert http.get("/api/admin/feedback").status_code == 401
    rows = owner(http).json()["feedback"]
    bug = next(row for row in rows if row["kind"] == "bug")
    assert bug["page"] == "/recap.html" and bug["message"] == "The recap page shows nothing on Safari."
    assert bug["contact"] == "reader@example.com"
    assert [row["kind"] for row in owner(http, kind="useful").json()["feedback"]] == ["useful"]


def test_missing_coverage_and_update_feedback_have_separate_owner_counts(client):
    http, store = client
    assert http.post("/api/feedback", json={"kind": "coverage"}).status_code == 422
    assert http.post("/api/feedback", json={"kind": "coverage", "message": "Missing https://www.bbc.com/news/tech-example"}).status_code == 204
    assert http.post("/api/feedback", json={"kind": "update_yes"}).status_code == 204
    assert {row["kind"] for row in feedback.summary(store, "2000-01-01")} == {"coverage", "update_yes"}


def test_coverage_review_reads_archive_without_visiting_the_reported_url(client):
    http, store = client
    auth = {"Authorization": "Bearer owner-key-for-tests-1234567890"}
    path = "/api/admin/coverage-review"
    url = "https://www.bbc.com/news/tech-example"
    assert http.post(path, json={"url": url}).status_code == 401
    missing = http.post(path, headers=auth, json={"url": url}).json()
    assert missing["status"] == "missing_from_retained_archive"
    store.ingest("bbc-tech", [{"id": "coverage-fixture", "source_id": "bbc-tech", "source": "bbc",
        "publisher": "BBC Technology", "title": "Report covers a major new software release", "description": "Technology release.",
        "kind": "blog", "category": "Technology", "url": url, "published_at": datetime.now(UTC).isoformat()}], True)
    indexed = http.post(path, headers=auth, json={"url": url + "?utm_source=test"})
    assert indexed.status_code == 200 and indexed.headers["cache-control"] == "private, no-store"
    assert indexed.json()["matches"][0]["id"] == "coverage-fixture"
    assert http.post(path, headers=auth, json={"url": "file:///local"}).status_code == 422


def test_feedback_validation_spam_trap_and_cross_site(client):
    http, store = client
    assert http.post("/api/feedback", json={"kind": "idea", "message": "x"}).status_code == 422
    assert http.post("/api/feedback", json={"kind": "idea", "message": "Add Rust", "contact": "not-an-email"}).status_code == 422
    assert http.post("/api/feedback", json={"kind": "shout", "message": "hello there"}).status_code == 422
    assert http.post("/api/feedback", json={"kind": "idea", "message": "m" * 2001}).status_code == 422
    assert http.post("/api/feedback", json={"kind": "idea", "message": "Buy cheap things", "website": "http://spam"}).status_code == 204
    assert http.post("/api/feedback", json={"kind": "idea", "message": "Add more Rust news", "page": "javascript:alert(1)"}).status_code == 204
    cross = http.post("/api/feedback", json={"kind": "idea", "message": "Hello there"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    rows = owner(http).json()["feedback"]
    assert [row["message"] for row in rows] == ["Add more Rust news"] and rows[0]["page"] == "/"


def test_feedback_is_rate_limited(client):
    http, _ = client
    codes = [http.post("/api/feedback", json={"kind": "idea", "message": f"Idea number {index}"}).status_code for index in range(8)]
    assert codes[:6] == [204] * 6 and codes[6] == 429


def test_old_feedback_is_deleted_and_summaries_have_counts_only(client):
    _, store = client
    old = time.time() - (feedback.RETENTION_DAYS + 1) * 86400
    feedback.record(store, feedback.Feedback(kind="idea", message="An old idea", page="/"), now=old)
    feedback.record(store, feedback.Feedback(kind="useful", page="/recap.html"))
    feedback.record(store, feedback.Feedback(kind="useful", page="/recap.html"))
    assert feedback.summary(store, "2000-01-01") == [{"kind": "useful", "page": "/recap.html", "count": 2}]


def test_monthly_report_shows_feedback_counts_but_never_messages(client):
    from scripts import curiosity_upkeep
    _, store = client
    assert "No feedback in the last 35 days" in curiosity_upkeep.feedback_section(35, lambda: store)
    feedback.record(store, feedback.Feedback(kind="bug", message="My email is private@example.com", page="/", contact="private@example.com"))
    feedback.record(store, feedback.Feedback(kind="useful", page="/recap.html"))
    feedback.record(store, feedback.Feedback(kind="not_useful", page="/recap.html"))
    section = curiosity_upkeep.feedback_section(35, lambda: store)
    assert "- bug: 1" in section and "`/recap.html`: 1 / 1" in section
    assert "private@example.com" not in section
