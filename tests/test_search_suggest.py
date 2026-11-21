from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import server
from app.search_suggest import match_score, suggest


def source(source_id, label, region="Global", enabled=True):
    return SimpleNamespace(id=source_id, label=label, region=region, enabled=enabled)


TOPICS = {"ai": "AI & Machine Learning", "security": "Cybersecurity & Privacy"}
SUBJECTS = {"kubernetes": "Kubernetes & containers", "llms": "LLMs & inference"}


def test_match_score_prefers_exact_then_prefix_then_word_then_substring():
    assert match_score("wired", "WIRED") > match_score("wir", "WIRED")
    assert match_score("wir", "WIRED") > match_score("verge", "The Verge")
    assert match_score("verge", "The Verge") > match_score("erge", "The Verge") > 0
    assert match_score("zzz", "The Verge") == 0


def test_suggest_groups_kinds_and_skips_disabled_sources():
    rows = suggest("ku", topics=TOPICS, subjects=SUBJECTS, sources=[
        source("k8s-blog", "Kubernetes Blog"), source("paused", "Kubernetes Paused", enabled=False),
    ], authors=[{"id": "author-1", "name": "Kumar Rao", "publisher": "DEV Community"}])
    assert [row["kind"] for row in rows] == ["subject", "publisher", "author"]
    assert rows[1] == {"kind": "publisher", "id": "k8s-blog", "label": "Kubernetes Blog", "detail": "Global"}
    assert rows[2]["detail"] == "DEV Community"


def test_suggest_ignores_short_queries_and_folds_accents():
    assert suggest("a", topics=TOPICS, subjects=SUBJECTS, sources=[]) == []
    rows = suggest("numé", topics={}, subjects={}, sources=[source("numerama", "Numérama")])
    assert rows and rows[0]["id"] == "numerama"


def test_suggest_caps_each_kind():
    sources = [source(f"s{i}", f"Cloud Weekly {i}") for i in range(10)]
    rows = suggest("cloud", topics={}, subjects={}, sources=sources)
    assert len(rows) == 5


def test_suggest_endpoint_uses_catalog_and_recent_authors(monkeypatch):
    server._suggest_cache.clear()
    monkeypatch.setattr(server, "get_store", lambda: None)
    monkeypatch.setattr(server, "intelligence_candidates", lambda store: [])
    response = TestClient(server.app).get("/api/search/suggest?q=secur")
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "secur"
    assert any(row["kind"] == "topic" and row["id"] == "security" for row in body["suggestions"])
    assert response.headers["cache-control"] == "public, max-age=60"
    assert TestClient(server.app).get("/api/search/suggest?q=" + "x" * 81).status_code == 422
