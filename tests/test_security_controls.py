import json
import re
from pathlib import Path
import ssl
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import public_mail, server
from app.launch_store import Store
from app.scrapers import web_content
from app.services import email


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_cross_origin_write_is_rejected_before_routing(method):
    with TestClient(server.app, base_url="https://news.example") as client:
        response = client.request(method, "/api/security-fixture", headers={"Origin": "https://other.example"})
        assert response.status_code == 403
        assert response.headers["Cache-Control"] == "no-store"
        assert "object-src 'none'" in response.headers["Content-Security-Policy"]
        assert client.request(method, "/api/security-fixture", headers={"Origin": "http://news.example"}).status_code == 403
        assert client.request(method, "/api/security-fixture", headers={"Origin": "https://news.example"}).status_code in {404, 405}


def test_delete_body_limit_and_content_length_validation():
    with TestClient(server.app) as client:
        assert client.request("DELETE", "/api/security-fixture", content=b" " * (server.MAX_REQUEST_BYTES + 1)).status_code == 413
        assert client.request("DELETE", "/api/security-fixture", headers={"Content-Length": "invalid"}).status_code == 400


def test_logout_persists_session_revocation(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'sessions.db'}"
    store = Store(url)
    monkeypatch.setattr(public_mail, "get_store", lambda: store)
    monkeypatch.setenv("MAIL_SESSION_SECRET", "local-fixture-secret-with-forty-characters")
    monkeypatch.delenv("MAIL_PILOT_MODE", raising=False)
    token = public_mail.seal("session", {"email": "reader@example.org", "nonce": "first-session"}, 600)
    other_session = public_mail.seal("session", {"email": "reader@example.org", "nonce": "other-session"}, 600)

    with TestClient(server.app) as client:
        client.cookies.set(public_mail.SESSION, token, path="/api/mail")
        assert client.post("/api/mail/workspace", json={"url": "https://example.org/workspace", "preview_id": "preview-test-id-000000000000"}).status_code == 422
        assert client.post("/api/mail/logout").status_code == 200

    store = Store(url)
    with TestClient(server.app) as client:
        client.cookies.set(public_mail.SESSION, token, path="/api/mail")
        assert client.post("/api/mail/workspace", json={"url": "https://example.org/workspace", "preview_id": "preview-test-id-000000000000"}).status_code == 401
        assert not store.mail_session_revoked(public_mail.digest_key("session-token:" + other_session))


def test_publisher_fetch_requires_reviewed_host(monkeypatch):
    def fetch(url):
        assert url == "https://www.anthropic.com/news/example"
        return b"<main><p>Reviewed source content.</p></main>"

    monkeypatch.setattr(web_content, "fetch_bytes", fetch)
    hosts = frozenset({"www.anthropic.com"})
    assert web_content.url_to_markdown("https://other.example/news/example", allowed_hosts=hosts) is None
    assert "Reviewed source content." in web_content.url_to_markdown(
        "https://www.anthropic.com/news/example", allowed_hosts=hosts)


def test_owner_mail_requires_certificate_and_hostname_verification(monkeypatch):
    smtp = MagicMock()
    monkeypatch.setattr(email.smtplib, "SMTP_SSL", smtp)
    monkeypatch.setattr(email, "MY_EMAIL", "sender@example.org")
    monkeypatch.setattr(email, "APP_PASSWORD", "local-test-only")
    email.send_email("Test", "Plain text")
    context = smtp.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    smtp.return_value.__enter__.return_value.sendmail.assert_called_once()


def test_every_static_html_route_has_an_edge_content_security_policy():
    root = Path(__file__).resolve().parents[1]
    configuration = json.loads((root / "vercel.json").read_text(encoding="utf-8"))
    paths = {entry["source"] for entry in configuration["headers"]
             if any(header["key"] == "Content-Security-Policy" for header in entry["headers"])}
    policies = [header["value"] for entry in configuration["headers"] for header in entry["headers"]
                if header["key"] == "Content-Security-Policy"]
    assert policies and all("https://vercel.live" in policy for policy in policies)
    for route in ("/", *("/" + page.name for page in (root / "public").glob("*.html"))):
        assert any(route == path or (
            path.startswith("/:page(") and re.fullmatch(path.removeprefix("/:page"), route.removeprefix("/"))
        ) for path in paths), route
