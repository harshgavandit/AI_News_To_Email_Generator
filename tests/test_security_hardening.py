"""Regression tests for the 2026-11-21 security audit fixes."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import public_mail, server
from app.client_identity import quota_network

OWNER = "owner-token-for-security-regressions-0123"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(server, "get_store", lambda: None)
    monkeypatch.setenv("ADMIN_TOKEN", OWNER)
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)


@pytest.fixture
def client():
    return TestClient(server.app, base_url="https://testserver")


def edge_request(address):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [
        (b"x-vercel-forwarded-for", address.encode())], "client": ("10.0.0.1", 1234)})


@pytest.mark.parametrize(("address", "network"), [
    ("203.0.113.9", "203.0.113.9"),
    ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
    ("2001:db8:1:2:ffff:ffff:ffff:fffe", "2001:db8:1:2::/64"),
    ("::ffff:198.51.100.4", "198.51.100.4"),
    ("[2001:db8::1]", "2001:db8::/64"),
    ("not-an-address", "not-an-address"),
])
def test_quota_network_groups_ipv6_by_64(address, network):
    assert quota_network(address) == network


def test_ipv6_rotation_shares_one_quota_bucket(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("MAIL_SESSION_SECRET", "s" * 40)
    first, rotated, other = (edge_request(ip) for ip in ("2001:db8:1:3::1", "2001:db8:1:3::beef", "2001:db8:1:4::1"))
    assert server.client_key(first) == server.client_key(rotated) != server.client_key(other)
    assert public_mail.address_key(first) == public_mail.address_key(rotated) != public_mail.address_key(other)
    # IPv4 identities are unchanged so existing quota buckets remain valid.
    assert server.client_key(edge_request("203.0.113.9")) == hashlib.sha256(b"203.0.113.9").hexdigest()


def test_rotating_ipv6_addresses_is_rate_limited(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    codes = [client.get("/api/discovery/check", params={"url": "https://example.com/story"},
                        headers={"x-vercel-forwarded-for": f"2001:db8:9:9::{index:x}"}).status_code
             for index in range(1, 40)]
    assert 429 in codes


def test_short_owner_token_is_rejected(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "short-token")
    response = client.post("/api/admin/sources", headers={"Authorization": "Bearer short-token"})
    assert response.status_code == 401
    assert server.signature({"a": 1}, 1) == ""


def test_owner_token_of_sufficient_length_is_accepted(client, monkeypatch):
    monkeypatch.setattr(server, "source_store", lambda: None)
    monkeypatch.setattr(server, "source_catalog", lambda store: [])
    response = client.post("/api/admin/sources", headers={"Authorization": f"Bearer {OWNER}"})
    assert response.status_code == 200


def test_repeated_privileged_auth_failures_are_throttled(client):
    statuses = [client.post("/api/admin/sources", headers={"Authorization": "Bearer wrong"}).status_code
                for _ in range(server.AUTH_FAILURE_LIMIT + 2)]
    assert statuses[:server.AUTH_FAILURE_LIMIT] == [401] * server.AUTH_FAILURE_LIMIT
    assert statuses[-1] == 429
    blocked = client.post("/api/admin/sources", headers={"Authorization": f"Bearer {OWNER}"})
    assert blocked.status_code == 429 and blocked.headers["Retry-After"]
    # Public routes are unaffected by the privileged throttle.
    assert client.get("/api/health").status_code == 200


def test_job_secret_failures_count_toward_throttle(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "c" * 40)
    for _ in range(server.AUTH_FAILURE_LIMIT):
        assert client.get("/api/jobs/mail-health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/jobs/mail-health", headers={"Authorization": "Bearer " + "c" * 40}).status_code == 429


def test_preview_signature_uses_a_derived_key():
    digest, expires = {"markdown": "x", "html": "<p>x</p>"}, 2_000_000_000
    message = json.dumps({"digest": digest, "expires": expires}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    raw = hmac.new(OWNER.encode(), message.encode(), hashlib.sha256).hexdigest()
    issued = server.signature(digest, expires)
    assert issued and issued != raw
    assert issued == server.signature(digest, expires)


def test_swagger_ui_is_off_in_production(client, monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert client.get("/api/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 200
    monkeypatch.setenv("API_DOCS_ENABLED", "1")
    assert client.get("/api/docs").status_code == 200


def test_swagger_ui_available_outside_production(client):
    response = client.get("/api/docs")
    assert response.status_code == 200 and "swagger" in response.text.lower()


def test_public_read_endpoints_have_a_budget(client, monkeypatch):
    monkeypatch.setattr(server, "READ_LIMITS", (("/api/authors", "read-authors", 3),))
    monkeypatch.setattr(server, "intelligence_candidates", lambda store, *args, **kwargs: [])
    statuses = [client.get("/api/authors").status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200] and statuses[-1] == 429


def test_security_headers_include_opener_isolation(client):
    response = client.get("/api/health")
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_cross_site_writes_are_still_rejected(client):
    response = client.post("/api/recommendations", json={}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
