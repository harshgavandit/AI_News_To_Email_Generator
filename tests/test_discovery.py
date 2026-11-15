from datetime import UTC, datetime, timedelta
import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import news, server
from app import discovery
from app.agent import openai_client
from app.launch_store import Store
from app.web_digest import build_digest, safe_email_html


def story(ident, title, hours_ago, description="", **extra):
    return dict(id=ident, title=title, description=description, source="openai", source_id="openai-news",
                publisher="OpenAI News", kind="news", category="News", url=f"https://openai.com/news/{ident}",
                published_at=(datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(), **extra)


@pytest.mark.parametrize("with_archive", [True, False])
def test_second_page_keeps_its_publication_window(monkeypatch, tmp_path, with_archive):
    now = datetime.now(UTC)
    clock = Mock(wraps=datetime)
    clock.now.return_value = now
    rows = [story("recent", "Recent story", 1), story("edge", "Near the 12 hour cutoff", 11.99)]
    store = Store(f"sqlite:///{tmp_path / 'rolling-window.db'}") if with_archive else None
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(discovery, "datetime", clock)
    if store:
        store.ingest("openai-news", rows, True)
    else:
        monkeypatch.setattr(server, "collect_news", lambda: {"articles": rows, "sources": []})
        monkeypatch.setattr(server, "datetime", clock)
    client = TestClient(server.app)
    first = client.get("/api/news?hours=12&limit=1").json()
    assert first["window_ends_at"] == now.isoformat()
    assert first["next_cursor"]
    clock.now.return_value = now + timedelta(minutes=5)
    second = client.get("/api/news", params={"hours": 12, "limit": 1, "cursor": first["next_cursor"]}).json()
    assert second["window_ends_at"] == first["window_ends_at"]
    assert second["total"] == 2
    assert [row["id"] for row in second["articles"]] == ["edge"]


@pytest.mark.parametrize("with_archive", [True, False])
def test_search_ranking_and_cursor_in_both_storage_modes(monkeypatch, tmp_path, with_archive):
    rows = [story("recent", "A retrieval update", 1, "Changes to vector search."),
            story("phrase", "Vector search release", 9),
            story("older", "Vector index adds search", 10),
            story("unrelated", "Infrastructure", 8)]
    archive = Store(f"sqlite:///{tmp_path / 'discovery.db'}") if with_archive else None
    monkeypatch.setattr(server, "get_store", lambda: archive)
    if archive:
        archive.ingest("openai-news", rows, True)
    else:
        monkeypatch.setattr(server, "collect_news", lambda: {"articles": rows, "sources": []})
    client = TestClient(server.app)
    for sort, expected in [("relevance", ["phrase", "older", "recent"]),
                           ("latest", ["recent", "phrase", "older"]),
                           ("oldest", ["older", "phrase", "recent"])]:
        params = {"hours": 12, "q": "vector search", "sort": sort, "limit": 1, "publisher": "openai-news"}
        cursor = None
        seen = []
        while True:
            response = client.get("/api/news", params=dict(params, cursor=cursor) if cursor else params)
            assert response.status_code == 200
            page = response.json()
            assert page["total"] == 3
            assert "search_score" not in page["articles"][0]
            seen.extend(a["id"] for a in page["articles"])
            cursor = page["next_cursor"]
            if not cursor:
                break
            assert client.get("/api/news", params=dict(params, sort="oldest" if sort != "oldest" else "latest",
                                                       cursor=cursor)).status_code == 400
        assert seen == expected


def test_chunked_request_size_limit_without_running_provider(monkeypatch):
    monkeypatch.setattr(server, "get_store", Mock(side_effect=AssertionError("Request must not reach route")))
    client = TestClient(server.app)
    body = iter([b'{"focus":"', b"x" * server.MAX_REQUEST_BYTES, b'"}'])
    response = client.post("/api/digest", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"


def test_degraded_synthesis_labels_excerpts_and_headlines(monkeypatch):
    from app.agent import curator_agent, digest_agent

    complete = Mock(side_effect=ValueError("private provider error"))
    monkeypatch.setattr(digest_agent, "generate_response", complete)
    monkeypatch.setattr(curator_agent, "generate_response", Mock(side_effect=AssertionError("Avoid additional provider call")))
    result = build_digest([story("headline", "Headline only", 1), story("release", "New runtime", 2,
                           "Release notes describe a runtime.")], "Reader", "runtime", pinned_ids=["release"])
    assert [a["digest_id"] for a in result["articles"]] == ["release", "headline"]
    assert [a["summary_basis"] for a in result["articles"]] == ["publisher_excerpt", "headline_only"]
    assert result["articles"][0]["summary"] == "Release notes describe a runtime."
    assert result["synthesis"] == {"degraded": True, "ranking": "selection_order", "ai_summaries": 0}
    assert "Publisher excerpt" in result["html"] and "Headline only" in result["markdown"]
    assert "private provider error" not in str(result)
    complete.assert_called_once()


def test_provider_retries_one_fast_connection_error(monkeypatch):
    from openai import APIConnectionError

    create = Mock(side_effect=[APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")),
                               Mock(choices=[Mock(message=Mock(content='{}'))])])
    monkeypatch.setattr(openai_client, "get_client", lambda: Mock(chat=Mock(completions=Mock(create=create))))
    monkeypatch.setattr(openai_client.time, "sleep", Mock())
    assert openai_client.generate_response("Fixture") == "{}"
    assert create.call_count == 2


def test_manual_direct_refresh_has_shared_cooldown(monkeypatch):
    from app.sources import BY_ID

    clock = [100]
    fetch = Mock(return_value=([], dict(BY_ID["openai-news"].public(), available=True)))
    monkeypatch.setattr(news.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(news, "DEFAULT_SOURCES", [BY_ID["openai-news"]])
    monkeypatch.setattr(news, "_cache", {})
    monkeypatch.setattr(news, "_refreshed", 0)
    monkeypatch.setattr(news, "read_feed", fetch)
    news.collect_news()
    news.collect_news(force=True)
    clock[0] += 31
    news.collect_news(force=True)
    news.collect_news()
    assert fetch.call_count == 2


def test_email_export_rejects_unsafe_story_links():
    rendered = safe_email_html({"articles": [{"title": "Unsafe link", "url": "javascript:alert(1)"}],
                                "quick_hits": [{"title": "Other link", "url": "data:text/html,test"}]})
    assert 'href="#"' in rendered
    assert "javascript:" not in rendered and "data:text/html" not in rendered


def test_legacy_video_without_excerpt_skips_ai_and_keeps_thumbnail(monkeypatch):
    from app.agent import digest_agent
    from app.coverage import public_article

    complete = Mock(side_effect=AssertionError("Headline-only entries do not need a model"))
    monkeypatch.setattr(digest_agent, "generate_response", complete)
    row = dict(story("video", "New runtime", 1, "Video by AI Engineer covering New runtime."),
               source="youtube", source_id="ai-engineer", publisher="AI Engineer", kind="video",
               url="https://www.youtube.com/watch?v=abcdefghijk")
    article = public_article(row)
    assert not article["has_excerpt"]
    assert article["thumbnail_url"] == "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"
    digest = build_digest([row], "Reader", "runtime")
    assert digest["articles"][0]["summary_basis"] == "headline_only"
    complete.assert_not_called()


def test_shared_generation_lease_blocks_same_brief(monkeypatch, tmp_path):
    from threading import Event, Thread
    from app.cache import Cache

    first = Store(f"sqlite:///{tmp_path / 'leases.db'}")
    second = Store(str(first.engine.url))
    body = server.DigestRequest(edition="world")
    entered, condition = Event(), Event()
    results = []

    def prepare(*args):
        entered.set()
        assert condition.wait(5)
        return {"articles": []}

    monkeypatch.setattr(server, "prepare_digest", prepare)
    monkeypatch.setattr(server, "_digest_cache", Cache("lease-first-test"))
    worker = Thread(target=lambda: results.append(server.assemble_digest(body, first)))
    worker.start()
    try:
        assert entered.wait(5)
        # Use another process-local cache and lock against the same shared database.
        monkeypatch.setattr(server, "_digest_cache", Cache("lease-second-test"))
        with pytest.raises(server.HTTPException) as error:
            server.assemble_digest(body, second)
        assert error.value.status_code == 429
    finally:
        condition.set()
        worker.join(timeout=5)
    assert len(results) == 1


def test_personal_stream_stores_the_source_linked_export(monkeypatch, tmp_path):
    from app.agent import digest_agent
    from app.cache import Cache

    store = Store(f"sqlite:///{tmp_path / 'preview.db'}")
    row = story("runtime", "Vector runtime release", 1, "The publisher released a vector runtime.")
    store.ingest("openai-news", [row], True)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(server, "_digest_cache", Cache("personal-stream-test"))
    monkeypatch.setattr(digest_agent, "generate_response", Mock(return_value=json.dumps({
        "title": row["title"], "summary": row["description"], "whyItMatters": "", "keyTakeaway": "",
    })))
    response = TestClient(server.app).post("/api/digest?stream=true", json={
        "top_n": 1, "focus": "vector runtime", "sources": ["openai-news"], "pinned_ids": [row["id"]],
    })
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["stage"] for event in events[:-1]] == [1, 2, 3]
    result = events[-1]["result"]
    digest = store.get_preview(result["preview_id"])
    assert digest == result["digest"]
    assert digest["articles"][0]["summary_basis"] == "ai_feed_summary"
    assert row["url"] in digest["html"] and row["url"] in digest["markdown"]
