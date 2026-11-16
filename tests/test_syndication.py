"""Private permission submissions, explicit owner review and immediate revocation."""
from datetime import UTC, datetime
import os
from uuid import uuid4

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url

from app import public_mail, server, syndication
from app.launch_store import Store, reading_permissions


BODY = "## Practical database indexing\n\n" + (
    "Measure the query plan before adding an index. An index can improve reads but adds storage and write work. " * 4
) + '\n\n```python\nprint("Explain the plan")\n```\n\n[Source](https://author.example/indexing)'


@pytest.fixture(params=["sqlite", "postgresql"])
def permission_database(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'permissions.db'}"
        return
    url = os.getenv("TEST_NEWS_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_NEWS_POSTGRES_URL to a disposable PostgreSQL service")
    schema_name = "test_reading_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f"CREATE SCHEMA {schema_name}")
    try:
        yield make_url(url).update_query_dict({"options": f"-csearch_path={schema_name}"}).render_as_string(hide_password=False)
    finally:
        with admin.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA {schema_name} CASCADE")
        admin.dispose()


@pytest.fixture
def workspace(permission_database, monkeypatch):
    store = Store(permission_database)
    store.migrate()
    monkeypatch.setenv("MAIL_SESSION_SECRET", "test-permission-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("ADMIN_TOKEN", "test-permission-owner")
    monkeypatch.delenv("MAIL_PILOT_MODE", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    for module in (server, syndication, public_mail):
        monkeypatch.setattr(module, "get_store", lambda: store)
    monkeypatch.setattr(public_mail, "ready", lambda: True)
    monkeypatch.setattr(server, "queue_archive_refresh", lambda _jobs, _store, _filters, _key, page, **_: page)
    server._news_cache.clear()
    store.ingest("medium-codex", [{"id": "permission-article", "source_id": "medium-codex", "source": "medium",
        "publisher": "CodeX on Medium", "kind": "engineering", "category": "Databases", "title": "An indexing guide",
        "description": "A short source excerpt.", "url": "https://medium.com/codex/indexing-abc123def456",
        "published_at": datetime.now(UTC).isoformat(), "author": "A Writer"}], True)
    author, owner, stranger = TestClient(server.app), TestClient(server.app), TestClient(server.app)
    author.cookies.set(public_mail.SESSION, public_mail.seal("session", "writer@example.org", 600), path="/api/mail")
    stranger.cookies.set(public_mail.SESSION, public_mail.seal("session", "different@example.org", 600), path="/api/mail")
    owner.headers["Authorization"] = "Bearer test-permission-owner"
    yield store, author, owner, stranger
    store.engine.dispose()


def payload(**extra):
    return {"article_id": "permission-article", "author_name": "A Writer", "body_markdown": BODY,
            "permission_evidence": "I am the author. The owner can verify the original publication and contact my verified inbox.",
            "grant_permission": True, "terms_version": syndication.TERMS_VERSION, **extra}


def test_end_to_end_private_submission_approval_reading_and_withdrawal(workspace):
    store, author, owner, stranger = workspace
    created = author.post("/api/mail/contributions", json=payload())
    assert created.status_code == 201
    ident = created.json()["id"]
    assert author.get("/api/mail/contributions/config").json()["permission_statement"] == syndication.GRANT
    public = stranger.get("/api/articles/permission-article").json()
    assert public["reading"] is None and public["article"]["reading_access"]["mode"] == "excerpt"
    assert stranger.get(f"/api/mail/contributions/{ident}").status_code == 404
    assert stranger.get("/api/admin/contributions").status_code == 401
    queue = owner.get("/api/admin/contributions").json()
    assert queue["submissions"][0]["verified_email"] == "writer@example.org"
    assert "body_markdown" not in queue["submissions"][0]
    detail = owner.get(f"/api/admin/contributions/{ident}")
    assert detail.status_code == 200 and "<pre><code" in detail.json()["preview_html"]
    assert detail.headers["cache-control"] == "no-store"
    review = {"action": "approve", "note": "Permission verified against the original publication.", "permission_verified": True}
    assert owner.post(f"/api/admin/contributions/{ident}/review", json={**review, "permission_verified": False}).status_code == 422
    assert owner.post(f"/api/admin/contributions/{ident}/review", json=review).json()["state"] == "approved"
    assert owner.post(f"/api/admin/contributions/{ident}/review", json=review).status_code == 409
    reading = stranger.get("/api/articles/permission-article")
    assert reading.headers["cache-control"] == "no-store"
    assert reading.json()["article"]["reading_access"]["mode"] == "full_text"
    assert "Practical database indexing" in reading.json()["reading"]["html"]
    assert "writer@example.org" not in reading.text and "permission_evidence" not in reading.text
    page = owner.get("/api/news?source=medium").json()
    assert page["articles"][0]["reading_access"]["mode"] == "full_text"
    assert stranger.post(f"/api/mail/contributions/{ident}/withdraw").status_code == 404
    assert author.post(f"/api/mail/contributions/{ident}/withdraw").json()["state"] == "withdrawn"
    assert stranger.get("/api/articles/permission-article").json()["reading"] is None
    assert owner.post(f"/api/admin/contributions/{ident}/review", json=review).status_code == 409
    with store.engine.connect() as conn:
        assert conn.scalar(select(reading_permissions.c.active)) is False


@pytest.mark.parametrize("update", [{"grant_permission": False}, {"terms_version": "old"},
                                  {"body_markdown": "Too short"}, {"permission_evidence": "mine"},
                                  {"article_id": "https://localhost"}, {"url": "https://127.0.0.1"}])
def test_invalid_submissions_are_rejected(workspace, update):
    _, author, _, _ = workspace
    assert author.post("/api/mail/contributions", json=payload(**update)).status_code == 422


def test_inbox_authentication_and_submission_quota(workspace):
    _, author, owner, _ = workspace
    assert owner.post("/api/mail/contributions", json=payload()).status_code == 401
    for _ in range(3):
        assert author.post("/api/mail/contributions", json=payload()).status_code == 201
    assert author.post("/api/mail/contributions", json=payload()).status_code == 429


def test_rejection_and_owner_revocation(workspace):
    _, author, owner, stranger = workspace
    first = author.post("/api/mail/contributions", json=payload()).json()["id"]
    assert owner.post(f"/api/admin/contributions/{first}/review", json={"action": "reject", "note": "Permission could not be independently verified."}).json()["state"] == "rejected"
    second = author.post("/api/mail/contributions", json=payload()).json()["id"]
    owner.post(f"/api/admin/contributions/{second}/review", json={"action": "approve", "note": "Permission independently verified.", "permission_verified": True})
    assert stranger.get("/api/articles/permission-article").json()["reading"]
    assert owner.post(f"/api/admin/contributions/{second}/review", json={"action": "revoke", "note": "Withdrawn after editorial review."}).json()["state"] == "revoked"
    assert stranger.get("/api/articles/permission-article").json()["reading"] is None


def test_untrusted_markdown_cannot_execute_or_load_remote_assets():
    attack = BODY + '\n<script>alert(1)</script><svg onload="bad()"></svg><img src="https://tracking.example/pixel"><iframe src="https://evil.example"></iframe><a href="javascript:bad()" onclick="bad()">bad link</a><div style="position:fixed" data-x="bad">Plain content</div>'
    clean = syndication.render_body(attack)
    soup = BeautifulSoup(clean, "html.parser")
    assert not soup.find(["script", "svg", "img", "iframe", "div"])
    for tag in soup.find_all(True):
        assert set(tag.attrs) <= ({"href", "rel", "target"} if tag.name == "a" else set())
    assert "javascript:" not in clean and "Plain content" in clean


def test_feed_metadata_cannot_self_grant_full_text(workspace):
    store, _, _, stranger = workspace
    original = store.article("permission-article")
    store.ingest("medium-codex", [{**original, "full_text": BODY,
        "reading_access": {"mode": "full_text"}, "body_markdown": BODY}], True)
    assert stranger.get("/api/articles/permission-article").json()["reading"] is None
