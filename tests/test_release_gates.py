import pytest
from fastapi.testclient import TestClient

from app.server import app
from scripts import check_production_release as production
from scripts.check_release_schema import DESTRUCTIVE_SQL, compare


def test_rejects_incompatible_schema_and_accepts_additive_column():
    identifier = {"type": "TEXT", "nullable": False, "default": False}
    before = {
        "articles": {"columns": {"id": identifier}, "primary_key": ["id"], "unique": []}
    }
    after = {
        "articles": {
            **before["articles"],
            "columns": {"id": identifier, "tag": {**identifier, "nullable": True}},
        }
    }
    assert compare(before, after) == []
    after["articles"]["columns"]["tag"]["nullable"] = False
    assert compare(before, after) == [
        "articles.tag: existing writers need a nullable column or server default"
    ]
    assert compare(before, {}) == ["articles: table removed or renamed"]
    assert DESTRUCTIVE_SQL.search("ALTER TABLE articles DROP COLUMN title")
    assert not DESTRUCTIVE_SQL.search("ALTER TABLE articles ADD COLUMN tag TEXT")


def test_health_identifies_deployed_revision(monkeypatch):
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "a" * 40)
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.json()["status"] == "ok"
    assert response.headers["X-Informa-Revision"] == "a" * 40
    assert response.headers["Cache-Control"] == "no-store"


def test_production_probe_checks_the_deployed_revision(monkeypatch):
    revision = "a" * 40
    required = {
        "/api/health": b'{"status": "ok"}',
        "/": b"Informa AI",
        "/research.html": b"Research Desk",
        "/api/news?hours=168&limit=1&catalog=0": b'{"articles": []}',
        "/feeds/latest.xml": b"<rss/>",
    }
    monkeypatch.setattr(production, "fetch", lambda path, _: (required[path], revision))
    production.verify(revision, 0)

    monkeypatch.setattr(production, "fetch", lambda path, _: (required[path], "b" * 40))
    with pytest.raises(SystemExit, match="Production smoke failed"):
        production.verify(revision, 0)

    required["/feeds/latest.xml"] = b"No RSS"
    monkeypatch.setattr(production, "fetch", lambda path, _: (required[path], revision))
    with pytest.raises(SystemExit, match="expected an RSS document"):
        production.verify(revision, 0)
