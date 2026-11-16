import asyncio
from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest

from app import hashnode, news, server
from app.article_metadata import author_identity
from app.sources import BY_ID
from app.intelligence import recommend
from fastapi.testclient import TestClient


def story(ident, *, source_id="dev-community", **metadata):
    source = BY_ID[source_id]
    return {"id": ident, "title": "A software programming guide", "description": "An author's source excerpt.",
            "url": f"https://{source.hosts[0]}/{ident}", "source_id": source_id, "source": source.group,
            "publisher": source.label, "kind": source.kind, "category": "software",
            "published_at": datetime.now(UTC).isoformat(), **metadata}


def post(ident="post", **extra):
    return {"id": ident, "title": "A practical Python programming guide", "slug": ident,
            "brief": "An author explains a working programming technique.", "url": f"https://writer.hashnode.dev/{ident}",
            "publishedAt": datetime.now(UTC).isoformat(), "author": {"name": "A Developer", "username": "developer"},
            "tags": [{"name": "Python", "slug": "python"}], "readTimeInMinutes": 4,
            "coverImage": {"url": "https://cdn.hashnode.com/res/image.jpg"}, **extra}


def page(*items, after=None):
    return {"data": {"feed": {"edges": [{"node": item} for item in items],
        "pageInfo": {"hasNextPage": bool(after), "endCursor": after}}}}


def mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(hashnode.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_hashnode_public_feed_paginates_and_rejects_future_private_and_off_topic_records(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        variables = json.loads(request.content)["variables"]
        if not variables["after"]:
            return httpx.Response(200, json=page(post(), post("future", publishedAt=(datetime.now(UTC) + timedelta(days=20)).isoformat()),
                post("private", url="https://127.0.0.1/article"),
                post("spam", title="Buy discount holiday tickets", brief="Tickets for a beach trip", tags=[]), after="cursor-one"))
        return httpx.Response(200, json=page(post(), post("second")))
    mock_client(monkeypatch, handler)
    rows, status = news.read_feed(BY_ID["hashnode-discover"])
    assert status["available"] and len(rows) == 2 and len(requests) == 2
    assert all(str(request.url) == hashnode.ENDPOINT for request in requests)
    assert all("authorization" not in request.headers for request in requests)
    assert all("content {" not in json.loads(request.content)["query"] for request in requests)
    assert rows[0]["author_url"] == "https://hashnode.com/@developer"
    assert rows[0]["reading_time_minutes"] == 4 and rows[0]["tags"] == ["python"]


@pytest.mark.parametrize("payload", [{"errors": [{"message": "Forbidden"}]}, {"data": None}, {"data": []},
                                     {"data": {"feed": {"edges": "invalid"}}}])
def test_invalid_or_gated_api_responses_are_not_retried_as_paid_post_queries(monkeypatch, payload):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)
    mock_client(monkeypatch, handler)
    rows, status = news.read_feed(BY_ID["hashnode-discover"])
    assert not rows and not status["available"] and len(calls) == 1


def test_hashnode_partial_page_failure_keeps_successful_records(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=page(post(), after="next")) if len(calls) == 1 else httpx.Response(503)
    mock_client(monkeypatch, handler)
    rows, status = news.read_feed(BY_ID["hashnode-discover"])
    assert status["available"] and len(rows) == 1


def test_hashnode_partial_rate_limit_keeps_rows_and_returns_retry_window(monkeypatch):
    def handler(request):
        if json.loads(request.content)["variables"]["after"]:
            return httpx.Response(429, headers={"Retry-After": "1800"})
        return httpx.Response(200, json=page(post(), after="next"))

    mock_client(monkeypatch, handler)
    rows, status = news.read_feed(BY_ID["hashnode-discover"])
    assert len(rows) == 1 and status["available"]
    assert status["error"] == "rate_limited" and status["retry_after"] == 1800


def test_hashnode_total_timeout_preserves_completed_pages(monkeypatch):
    real_timeout = asyncio.timeout
    monkeypatch.setattr(hashnode.asyncio, "timeout", lambda _: real_timeout(.05))
    calls = []
    async def handler(request):
        calls.append(request)
        if len(calls) > 1:
            await asyncio.sleep(1)
        return httpx.Response(200, json=page(post(), after="next"))
    mock_client(monkeypatch, handler)
    rows, status = news.read_feed(BY_ID["hashnode-discover"])
    assert status["available"] and len(rows) == 1


def test_hashnode_repeated_cursors_cannot_run_forever(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=page(post(), after="same-cursor"))
    mock_client(monkeypatch, handler)
    rows, status = news.read_feed(BY_ID["hashnode-discover"])
    assert status["available"] and len(calls) == 2 and len(rows) == 1


def test_following_an_author_uses_profile_identity_and_boosts_their_articles():
    first = story("first", author="Shared Display Name", author_url="https://dev.to/one")
    second = story("second", author="Shared Display Name", author_url="https://dev.to/two")
    key = author_identity(first)
    assert key != author_identity(second)
    result = recommend([second, first], authors=[key], limit=2)
    assert result["articles"][0]["id"] == "first"
    assert "From an author you follow" in result["articles"][0]["recommendation_reasons"]


def test_rss_author_names_are_scoped_to_their_source():
    assert author_identity(story("one", author="Same Name", source_id="medium-codex")) != author_identity(
        story("two", author="Same Name", source_id="medium-programming"))


def test_author_catalog_and_recommendation_request_use_real_observed_identities(monkeypatch):
    articles = [story("one", author="A Developer", author_url="https://dev.to/one"),
                story("two", author="A Different Developer", author_url="https://dev.to/two")]
    monkeypatch.setattr(server, "get_store", lambda: None)
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": articles, "sources": []})
    server._limits.clear()
    with TestClient(server.app) as client:
        authors = client.get("/api/authors?q=A+Developer").json()["authors"]
        assert len(authors) == 1 and authors[0]["id"] == author_identity(articles[0])
        recommended = client.post("/api/recommendations", json={"authors": [authors[0]["id"]]}).json()
        assert recommended["articles"][0]["id"] == "one"
        assert client.post("/api/recommendations", json={"authors": ["unvalidated-user"]}).status_code == 422
