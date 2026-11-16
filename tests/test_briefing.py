from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import server
from app.briefing import build_briefing
from app.sources import BY_ID


def article(ident, source_id="techcrunch", title="A new cloud deployment", age=1):
    source = BY_ID[source_id]
    return {"id": ident, "source_id": source.id, "source": source.group, "kind": source.kind,
            "title": title, "description": "The publisher describes a technology development.",
            "publisher": source.label, "url": f"https://{source.hosts[0]}/{ident}", "category": "News",
            "published_at": (datetime.now(UTC) - timedelta(hours=age)).isoformat()}


def test_briefing_groups_close_coverage_and_omits_ineligible_records():
    title = "Aster recalls 200 satellite terminals after battery overheating reports"
    rows = [article("one", title=title), article("two", "the-verge", title + " emerge"),
            article("research", "joss", "A numerical research software package"),
            article("security", "the-hacker-news", "A new vulnerability in a web framework"),
            article("old", age=48), article("future", age=-1),
            article("community", "dev-community"), article("video", "karpathy")]
    result = build_briefing(rows)
    assert result["total_candidates"] == 4
    assert len(result["articles"]) == 3
    lead, = [row for row in result["articles"] if row["id"] in {"one", "two"}]
    assert lead["coverage_count"] == 2
    assert set(lead["coverage_publishers"]) == {"TechCrunch", "The Verge"}
    assert {row["id"] for row in result["articles"]} & {"old", "future", "community", "video"} == set()
    assert all(row["summary_basis"] == "publisher_excerpt" for row in result["articles"])


def test_briefing_empty_and_invalid_dates_are_handled():
    assert build_briefing([])["articles"] == []
    rows = [dict(article("invalid"), published_at="missing date")]
    assert build_briefing(rows)["publishers"] == 0


def test_briefing_api_is_bounded_and_independent_of_ai(monkeypatch):
    monkeypatch.setattr(server, "get_store", lambda: None)
    monkeypatch.setattr(server, "intelligence_candidates", lambda *_: [article("real-record")])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    server._briefing_cache.clear()
    with TestClient(server.app) as client:
        response = client.get("/api/briefing")
        assert response.status_code == 200
        assert response.json()["articles"][0]["id"] == "real-record"
        assert response.headers["Vercel-CDN-Cache-Control"] == "public, s-maxage=30"
        assert client.get("/api/briefing?hours=99999").status_code == 422
    server._briefing_cache.clear()
