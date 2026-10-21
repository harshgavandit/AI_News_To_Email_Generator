import copy
import time
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import news as feeds
from app import server
from app.agent.curator_agent import CuratorAgent
from app.profiles.user_profile import USER_PROFILE
from app.web_digest import safe_email_html


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-owner-token")
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-key")
    monkeypatch.setenv("MY_EMAIL", "owner@example.com")
    monkeypatch.setenv("APP_PASSWORD", "test-app-password")
    server._limits.clear()
    server._digest_cache.clear()
    server._mail_history.clear()


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def article():
    return {"id": "test-id", "title": "Useful AI research", "description": "A new retrieval method.",
            "url": "https://openai.com/news/test", "source": "openai", "publisher": "OpenAI News",
            "published_at": datetime.now(timezone.utc).isoformat(), "category": "Research"}


@pytest.fixture
def digest():
    return {"introduction": {"greeting": "Hey Reader", "introduction": "Your latest AI news."},
            "articles": [{"title": "Research", "summary": "A finding.", "url": "https://openai.com/test"}],
            "html": "<p>Digest</p>", "markdown": "Digest"}


def signed(digest):
    expires = int(time.time()) + 3600
    return {"digest": digest, "expires": expires, "signature": server.signature(digest, expires)}


def test_home_assets_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Brief" in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    for path in ("/styles.css", "/app.js", "/favicon.svg"):
        assert client.get(path).status_code == 200


def test_api_starts_when_vercel_omits_public_directory(monkeypatch):
    import runpy
    from pathlib import Path
    original = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda path: False if path == server.PUBLIC else original(path))
    deployed = runpy.run_path(str(Path("app/server.py")))
    assert TestClient(deployed["app"]).get("/api/health").status_code == 200


def test_health_has_no_credentials(client):
    response = client.get("/api/health")
    assert response.json() == {"status": "ok", "ai_configured": True, "email_configured": True}
    assert "owner@example.com" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_missing_configuration(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    assert client.post("/api/digest", json={}).status_code == 503
    monkeypatch.delenv("APP_PASSWORD")
    assert client.get("/api/health").json()["email_configured"] is False


def test_news_filters_without_mutating_cache(client, article, monkeypatch):
    payload = {"articles": [article, dict(article, id="other", source="anthropic", title="Different")], "sources": [], "fetched_at": "now"}
    monkeypatch.setattr(server, "collect_news", lambda: payload)
    result = client.get("/api/news?source=openai&q=retrieval").json()
    assert result["total"] == 1
    assert len(payload["articles"]) == 2
    assert client.get("/api/news?q=nomatch").json()["total"] == 0


@pytest.mark.parametrize("hours", [24, 168, 720])
def test_news_accepts_browser_time_window_queries(client, article, monkeypatch, hours):
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": [article], "sources": []})
    response = client.get(f"/api/news?hours={hours}")
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("body", [{"top_n": 99}, {"hours": 100}, {"sources": []}, {"sources": ["unknown"]}, {"focus": "x" * 401}])
def test_generation_validates_inputs(client, body):
    assert client.post("/api/digest", json=body).status_code == 422


def test_generated_digest_is_cached_and_signed(client, article, digest, monkeypatch):
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": [article], "sources": []})
    build = Mock(return_value=digest)
    monkeypatch.setattr(server, "build_digest", build)
    first = client.post("/api/digest", json={})
    assert first.status_code == 200
    assert first.json()["signature"] == server.signature(digest, first.json()["expires"])
    assert client.post("/api/digest", json={}).status_code == 200
    assert build.call_count == 1
    assert client.post("/api/digest", json={}).status_code == 200
    assert client.post("/api/digest", json={}).status_code == 429


def test_empty_feed_does_not_call_model(client, monkeypatch):
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": [], "sources": []})
    build = Mock()
    monkeypatch.setattr(server, "build_digest", build)
    assert client.post("/api/digest", json={}).status_code == 404
    build.assert_not_called()


def test_model_failure_is_actionable_and_releases_lock(client, article, monkeypatch):
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": [article], "sources": []})
    monkeypatch.setattr(server, "build_digest", Mock(side_effect=ValueError("private provider details")))
    response = client.post("/api/digest", json={})
    assert response.status_code == 502
    assert "private provider details" not in response.text
    assert not server._generation_lock.locked()


def test_cross_origin_generation_rejected(client):
    assert client.post("/api/digest", json={}, headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_email_authentication_precedes_delivery(client, digest, monkeypatch):
    send = Mock()
    monkeypatch.setattr(server, "send_email", send)
    assert client.post("/api/email", json=signed(digest)).status_code == 401
    send.assert_not_called()


def test_email_rejects_changed_or_expired_preview(client, digest, monkeypatch):
    send = Mock()
    monkeypatch.setattr(server, "send_email", send)
    body = signed(digest)
    body["digest"]["html"] = "tampered"
    assert client.post("/api/email", json=body, headers={"Authorization": "Bearer test-owner-token"}).status_code == 400
    body = signed(digest)
    body["expires"] = 1
    assert client.post("/api/email", json=body, headers={"Authorization": "Bearer test-owner-token"}).status_code == 400
    send.assert_not_called()


def test_email_only_sends_to_owner_and_blocks_repeat(client, digest, monkeypatch):
    send = Mock()
    monkeypatch.setattr(server, "send_email", send)
    body = signed(digest)
    headers = {"Authorization": "Bearer test-owner-token"}
    assert client.post("/api/email", json=body, headers=headers).status_code == 200
    assert send.call_args.kwargs["recipients"] == ["owner@example.com"]
    assert client.post("/api/email", json=body, headers=headers).status_code == 409
    assert send.call_count == 1


def test_missing_gmail_is_reported(client, digest, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD")
    assert client.post("/api/email", json=signed(digest), headers={"Authorization": "Bearer test-owner-token"}).status_code == 503


def test_email_failure_allows_retry(client, digest, monkeypatch):
    monkeypatch.setattr(server, "send_email", Mock(side_effect=OSError("private failure")))
    response = client.post("/api/email", json=signed(digest), headers={"Authorization": "Bearer test-owner-token"})
    assert response.status_code == 502
    assert "private failure" not in response.text
    assert not server._mail_history


def test_email_escapes_generated_text(digest):
    digest["introduction"]["greeting"] = '<img src=x onerror="alert(1)">'
    digest["articles"][0]["summary"] = "<script>bad()</script>"
    result = safe_email_html(digest)
    assert "<script>" not in result
    assert "<img" not in result
    assert "&lt;script&gt;" in result


def test_feed_drops_unsafe_links(monkeypatch):
    content = b'''<rss version="2.0"><channel><title>Test</title><item><title>Bad</title><link>https://evil.example/x</link><pubDate>Tue, 20 Oct 2026 10:00:00 GMT</pubDate></item><item><title>Safe</title><link>https://openai.com/test</link><pubDate>Tue, 20 Oct 2026 10:00:00 GMT</pubDate><description>&lt;b&gt;Source text&lt;/b&gt;</description></item></channel></rss>'''
    response = Mock(content=content)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response
    monkeypatch.setattr(feeds.httpx, "Client", Mock(return_value=client))
    articles, source = feeds.read_feed(("openai", "OpenAI", "https://openai.com/news/rss.xml"))
    assert len(articles) == 1 and source["available"]
    assert articles[0]["description"] == "Source text"


def test_curator_rejects_hallucinated_source_ids(monkeypatch):
    from app.agent import curator_agent
    monkeypatch.setattr(curator_agent, "generate_response", lambda *a, **kw: '{"articles":[{"digest_id":"invented","rank":1,"relevance_score":9,"reasoning":"test"}]}')
    assert CuratorAgent(copy.deepcopy(USER_PROFILE)).rank_digests([{"id": "real", "title": "Source", "summary": "Text", "article_type": "openai"}]) == []
