import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import public_mail, server, workspace_delivery
from app.launch_store import Store
from app.sanitation import sanitize_story_excerpt


def test_excerpt_removes_sponsors_and_keeps_editorial_content():
    raw = ("👉🏻 A new runtime reduces cold start latency. Thanks to CoreWeave for sponsoring.\n"
           "Apply for an ARENA pass\nUse code DEMO\nDiscord: https://discord.gg/x\n"
           "🔗 X: @creator\n#CoreWeavePartner\nA second release improves compatibility. ✅")
    assert sanitize_story_excerpt(raw, "youtube") == (
        "A new runtime reduces cold start latency. A second release improves compatibility.")
    assert sanitize_story_excerpt("Join the Frontier\nSpotify: https://spotify.com/show", "youtube",
                                  "New runtime released", channel="AI Engineer") == (
        "Video by AI Engineer covering New runtime released.")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'enterprise.db'}")
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(workspace_delivery, "get_store", lambda: store)
    monkeypatch.setenv("MAIL_SESSION_SECRET", "long-test-secret-only-for-enterprise-tests")
    monkeypatch.delenv("MAIL_PILOT_MODE", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    server._digest_cache.clear()
    server._news_cache.clear()
    client = TestClient(server.app)
    return store, client


def test_archive_counts_cache_force_limit_and_pinned_stream(workspace):
    store, client = workspace
    story = {"id": "pinned-article", "title": "AI tools update", "description": "A new release.",
             "url": "https://openai.com/news/test", "source": "openai", "publisher": "OpenAI News",
             "published_at": datetime.now(UTC).isoformat(), "category": "News"}
    store.ingest("openai-news", [story], True)
    first = client.get("/api/news?hours=24")
    assert first.json()["source_counts"] == {"all": 1, "openai": 1}
    assert first.headers["X-Cache"] == "MISS"
    assert client.get("/api/news?hours=24").headers["X-Cache"] == "HIT"
    for _ in range(3):
        assert client.get("/api/news?hours=24&force=true").status_code == 200
    assert client.get("/api/news?hours=24&force=true").status_code == 429
    body = {"edition": "world", "pinnedStoryIds": [story["id"]], "sources": ["anthropic"]}
    stream = client.post("/api/digest?stream=true", json=body)
    events = [json.loads(line) for line in stream.text.splitlines()]
    assert [event["stage"] for event in events[:-1]] == [1, 3]
    assert events[-1]["result"]["digest"]["articles"][0]["digest_id"] == story["id"]
    assert client.post("/api/digest", json=body).headers["X-Cache"] == "HIT"


def test_sliding_window_does_not_reset_at_hour_boundary(workspace, monkeypatch):
    from app import launch_store

    store, _ = workspace
    times = iter([3599.0, 3601.0, 7200.0])
    monkeypatch.setattr(launch_store.time, "time", lambda: next(times))
    policy = [("sample", 3600, 1)]
    assert store.admit_windows(policy) is None
    assert store.admit_windows(policy) == 3599
    assert store.admit_windows(policy) is None


def test_workspace_dispatch_checks_recipient_and_url_and_is_idempotent(workspace, monkeypatch):
    store, client = workspace
    preview = "test-preview-id-abcdefghijklmnop"
    store.save_preview(preview, {"articles": [{"title": "<!channel> published a report", "url": "https://openai.com/test"}]},
                       datetime.now(UTC).timestamp() + 3600)
    request = {"url": "https://hooks.slack.com/services/T123/B456/fake-token", "preview_id": preview}
    assert client.post("/api/deliver/webhook", json=request).status_code == 401
    client.cookies.set(public_mail.SESSION, public_mail.seal("session", "reader@example.org", 600))
    assert client.post("/api/deliver/webhook", json={**request, "url": "https://hooks.slack.com.evil.example/services/T/B/X"}).status_code == 422
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    transport = Mock()
    transport.__enter__ = Mock(return_value=transport)
    transport.__exit__ = Mock(return_value=False)
    transport.stream.return_value = response
    monkeypatch.setattr(workspace_delivery.httpx, "Client", Mock(return_value=transport))
    for _ in range(2):
        assert client.post("/api/deliver/webhook", json=request).json()["status"] == "accepted"
    assert transport.stream.call_count == 1
    blocks = transport.stream.call_args.kwargs["json"]["blocks"]
    assert blocks[-1]["text"]["type"] == "plain_text"
    assert blocks[-1]["accessory"]["url"] == "https://openai.com/test"
