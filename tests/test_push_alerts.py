from datetime import UTC, datetime, timedelta
import json
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import pytest

from app import push_alerts
from app.launch_store import Store
from app.push_alerts import b64, unb64

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123-device-token"


def browser_keys():
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, b64(public), b64(b"0123456789abcdef")


def decrypt(body, browser_key, p256dh, auth):
    """The browser side of RFC 8291, written independently from the server code."""
    salt, record, length = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    server_public, ciphertext = body[21:21 + length], body[21 + length:]
    assert record == 4096 and length == 65
    shared = browser_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_public))
    ikm = HKDF(hashes.SHA256(), 32, salt=unb64(auth), info=b"WebPush: info\x00" + unb64(p256dh) + server_public).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


@pytest.fixture
def vapid(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv("NEWS_PUSH_VAPID_PRIVATE_KEY", b64(key.private_numbers().private_value.to_bytes(32, "big")))
    monkeypatch.setenv("NEWS_PUSH_SUBJECT", "mailto:alerts@example.com")
    return key


def test_payload_is_encrypted_for_the_browser_and_readable_only_with_its_keys():
    browser, p256dh, auth = browser_keys()
    body = push_alerts.encrypt(b'{"title":"Kubernetes 1.36"}', p256dh, auth)
    assert b"Kubernetes" not in body
    assert decrypt(body, browser, p256dh, auth) == b'{"title":"Kubernetes 1.36"}'
    other, _, _ = browser_keys()
    with pytest.raises(Exception):
        decrypt(body, other, p256dh, auth)


def test_vapid_token_is_signed_for_the_push_service_origin(vapid):
    key = push_alerts.vapid_key()
    header = push_alerts.vapid_authorization(ENDPOINT, key, now=1_800_000_000)
    token, public = header.removeprefix("vapid t=").split(", k=")
    head, claims, signature = token.split(".")
    assert json.loads(unb64(claims)) == {"aud": "https://fcm.googleapis.com", "exp": 1_800_043_200,
                                          "sub": "mailto:alerts@example.com"}
    raw = unb64(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(public)).verify(
        der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    assert public == push_alerts.public_key(vapid)


@pytest.mark.parametrize("endpoint,ok", [
    (ENDPOINT, True),
    ("https://updates.push.services.mozilla.com/wpush/v2/gAAAA", True),
    ("https://web.push.apple.com/QGmN0abc", True),
    ("https://wns2-bl2p.notify.windows.com/w/?token=abc", True),
    ("http://fcm.googleapis.com/fcm/send/abc123-device-token", False),
    ("https://fcm.googleapis.com.evil.example/fcm/send/abc", False),
    ("https://evil.example/?fcm.googleapis.com", False),
    ("https://user:pass@fcm.googleapis.com/fcm/send/abc123", False),
    ("https://fcm.googleapis.com:8443/fcm/send/abc123-device", False),
    ("https://127.0.0.1/fcm/send/abc123-device-token", False),
])
def test_only_known_push_services_are_accepted(endpoint, ok):
    assert push_alerts.valid_endpoint(endpoint) is ok


def test_disabled_without_a_key_and_a_bad_key_does_not_crash(monkeypatch):
    monkeypatch.delenv("NEWS_PUSH_VAPID_PRIVATE_KEY", raising=False)
    assert push_alerts.vapid_key() is None and not push_alerts.enabled()
    monkeypatch.setenv("NEWS_PUSH_VAPID_PRIVATE_KEY", "not-a-key")
    assert push_alerts.vapid_key() is None
    assert push_alerts.dispatch(object()) == {"push_status": "disabled"}


@pytest.fixture
def push_api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import push_api as api, server

    store = Store(f"sqlite:///{(tmp_path / 'push.sqlite').as_posix()}")
    store.migrate()
    monkeypatch.setattr(api, "get_store", lambda: store)
    server._limits.clear()
    yield TestClient(server.app, base_url="https://testserver"), store


def subscription_body(**profile):
    _, p256dh, auth = browser_keys()
    return {"subscription": {"endpoint": ENDPOINT, "keys": {"p256dh": p256dh, "auth": auth}, "expirationTime": None},
            "profile": {"feedback": {"companies": ["Nvidia"]}, **profile},
            "settings": {"max_per_day": 3, "quiet_hours": True, "timezone": "Asia/Kolkata"}}


def test_config_reports_availability(push_api, vapid, monkeypatch):
    client, _ = push_api
    config = client.get("/api/push/config").json()
    assert config["enabled"] is True and config["public_key"] == push_alerts.public_key(vapid)
    monkeypatch.delenv("NEWS_PUSH_VAPID_PRIVATE_KEY")
    assert client.get("/api/push/config").json() == {**config, "enabled": False, "public_key": None}


def test_subscription_stores_only_follows_and_can_be_removed(push_api, vapid):
    client, store = push_api
    body = subscription_body(followed_technologies=[], language="hi", name="Asha", interests=["vector databases"])
    saved = client.put("/api/push/subscription", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["follows"] == 2
    row = push_alerts.find(store, ENDPOINT)
    profile = json.loads(row["profile"])
    assert profile["feedback"] == {"companies": ["Nvidia"], "muted_topics": []}
    assert "name" not in profile and "language" not in profile and "Asha" not in row["profile"]
    assert json.loads(row["settings"])["timezone"] == "Asia/Kolkata"
    assert client.put("/api/push/subscription", json=body).status_code == 200
    assert push_alerts.count(store) == 1
    assert client.post("/api/push/subscription/remove", json={"endpoint": ENDPOINT}).status_code == 204
    assert push_alerts.find(store, ENDPOINT) is None


def test_subscription_validation(push_api, vapid, monkeypatch):
    client, _ = push_api
    bad_host = subscription_body()
    bad_host["subscription"]["endpoint"] = "https://attacker.example/collect"
    assert client.put("/api/push/subscription", json=bad_host).status_code == 422
    bad_key = subscription_body()
    bad_key["subscription"]["keys"]["p256dh"] = b64(b"short")
    assert client.put("/api/push/subscription", json=bad_key).status_code == 422
    nothing = subscription_body()
    nothing["profile"] = {}
    response = client.put("/api/push/subscription", json=nothing)
    assert response.status_code == 422 and "Follow" in response.json()["detail"]
    zone = subscription_body()
    zone["settings"]["timezone"] = "Mars/Olympus"
    assert client.put("/api/push/subscription", json=zone).json()["settings"]["timezone"] == "UTC"
    cross = client.put("/api/push/subscription", json=subscription_body(), headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    monkeypatch.delenv("NEWS_PUSH_VAPID_PRIVATE_KEY")
    assert client.put("/api/push/subscription", json=subscription_body()).status_code == 503


def test_rotation_keeps_follows_and_test_alert_reaches_the_push_service(push_api, vapid, monkeypatch):
    client, store = push_api
    assert client.put("/api/push/subscription", json=subscription_body()).status_code == 200
    replacement = subscription_body()["subscription"]
    replacement["endpoint"] = "https://fcm.googleapis.com/fcm/send/new-device-token"
    moved = client.post("/api/push/subscription/rotate", json={"old_endpoint": ENDPOINT, "subscription": replacement})
    assert moved.status_code == 204
    assert push_alerts.find(store, ENDPOINT) is None
    assert json.loads(push_alerts.find(store, replacement["endpoint"])["profile"])["feedback"]["companies"] == ["Nvidia"]
    sent = []

    class Sender:
        @staticmethod
        def post(url, **kwargs):
            sent.append((url, kwargs))
            return type("R", (), {"status_code": 201})()

    monkeypatch.setattr(push_alerts, "httpx", type("H", (), {"post": Sender.post, "HTTPError": Exception}))
    assert client.post("/api/push/test", json={"endpoint": replacement["endpoint"]}).json() == {"status": "sent"}
    url, request = sent[0]
    assert url == replacement["endpoint"] and request["follow_redirects"] is False
    assert request["headers"]["Content-Encoding"] == "aes128gcm" and request["headers"]["Authorization"].startswith("vapid t=")
    assert client.post("/api/push/test", json={"endpoint": ENDPOINT}).status_code == 404


def event(ident, title, *, hours_ago=1, version="1", topic="ai", sources=3):
    moment = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    article = {"title": title, "cleanSummary": "", "topic": topic, "publisher_family": f"family-{ident}",
               "published_at": moment, "url": "https://example.com/" + ident}
    return {"id": ident, "title": title, "topic": topic, "created_at": moment, "updated_at": moment,
            "digest_version": version, "source_count": sources, "articles": [article]}


def subscribe(store, endpoint=ENDPOINT, *, since=None, settings=None, profile=None):
    _, p256dh, auth = browser_keys()
    push_alerts.save(store, endpoint, p256dh, auth,
                     profile or {"followed_events": [], "followed_technologies": [], "stack": [], "topics": [], "interests": [],
                                 "feedback": {"companies": ["Nvidia"], "muted_topics": []}},
                     settings or {"max_per_day": 3, "quiet_hours": False, "timezone": "UTC"},
                     now=since or (datetime.now(UTC) - timedelta(hours=6)).timestamp())


@pytest.fixture
def push_store(tmp_path):
    store = Store(f"sqlite:///{(tmp_path / 'dispatch.sqlite').as_posix()}")
    store.migrate()
    return store


def test_dispatch_sends_one_alert_for_followed_coverage_once(push_store, vapid):
    subscribe(push_store)
    events = [event("a" * 32, "Nvidia ships a new inference chip"), event("b" * 32, "Unrelated database news"),
              event("c" * 32, "Nvidia earnings call notes", hours_ago=12)]
    sent = []
    send = lambda row, message: sent.append(message) or 201  # noqa: E731
    result = push_alerts.dispatch(push_store, events=events, send=send)
    assert result == {"push_status": "checked", "push_checked": 1, "push_sent": 1, "push_removed": 0}
    assert sent == [{"title": "Nvidia ships a new inference chip", "body": "Mentions a company you follow: Nvidia · 3 sources",
                     "url": f"/development.html?id={'a' * 32}", "tag": f"informa-{'a' * 32}"}]
    # Coverage older than the subscription is skipped; the gap blocks an immediate second alert.
    later = datetime.now(UTC).timestamp() + 4 * 3600
    assert push_alerts.dispatch(push_store, events=events, send=send, now=later)["push_sent"] == 0
    updated = [event("a" * 32, "Nvidia ships a new inference chip", version="2")]
    assert push_alerts.dispatch(push_store, events=updated, send=send, now=later)["push_sent"] == 1
    assert len(sent) == 2


def test_dispatch_respects_daily_limit_quiet_hours_and_gap(push_store, vapid):
    now = datetime(2026, 11, 24, 14, 30, tzinfo=UTC).timestamp()  # 20:00 in Kolkata
    subscribe(push_store, since=now - 3600, settings={"max_per_day": 1, "quiet_hours": True, "timezone": "Asia/Kolkata"})

    def at(ident, moment):
        return [dict(event(ident * 32, f"Nvidia update {ident}"), updated_at=datetime.fromtimestamp(moment, UTC).isoformat())]

    sent = []
    send = lambda row, message: sent.append(message) or 201  # noqa: E731
    assert push_alerts.dispatch(push_store, events=at("a", now - 60), send=send, now=now)["push_sent"] == 1
    # 23:30 in Kolkata is inside quiet hours.
    assert push_alerts.dispatch(push_store, events=at("b", now + 3 * 3600), send=send, now=now + 3.5 * 3600)["push_sent"] == 0
    # 10:00 the next day: a new local day, so the daily limit resets.
    assert push_alerts.dispatch(push_store, events=at("b", now + 3 * 3600), send=send, now=now + 14 * 3600)["push_sent"] == 1
    # 14:00 the same day: four hours later, but the one-a-day limit is used.
    assert push_alerts.dispatch(push_store, events=at("c", now + 15 * 3600), send=send, now=now + 18 * 3600)["push_sent"] == 0
    assert len(sent) == 2


def test_dispatch_removes_expired_and_failing_subscriptions(push_store, vapid):
    subscribe(push_store)
    subscribe(push_store, "https://updates.push.services.mozilla.com/wpush/v2/broken")
    events = [event("a" * 32, "Nvidia news")]
    gone = lambda row, message: 410 if "fcm" in row["endpoint"] else 500  # noqa: E731
    first = push_alerts.dispatch(push_store, events=events, send=gone)
    assert first["push_removed"] == 1 and push_alerts.count(push_store) == 1
    for _ in range(push_alerts.MAX_FAILURES - 1):
        push_alerts.dispatch(push_store, events=events, send=gone)
    assert push_alerts.count(push_store) == 0


def test_followed_stories_and_muted_topics(push_store, vapid):
    story = "d" * 32
    subscribe(push_store, profile={"followed_events": [story], "followed_technologies": [], "stack": [], "topics": [],
                                   "interests": [], "feedback": {"companies": ["Nvidia"], "muted_topics": ["security"]}})
    events = [event(story, "Outage postmortem published", sources=5),
              event("e" * 32, "Nvidia driver flaw", topic="security")]
    sent = []
    push_alerts.dispatch(push_store, events=events, send=lambda row, message: sent.append(message) or 201)
    assert sent[0]["title"] == "Outage postmortem published" and sent[0]["body"].startswith("You follow this story")


def test_intelligence_job_reports_push_without_failing(monkeypatch):
    from app import server

    monkeypatch.setattr(server.push_alerts, "dispatch", lambda store: (_ for _ in ()).throw(RuntimeError("boom")))
    assert server.send_push_alerts(object()) == {"push_status": "failed"}


def test_push_storage_works_on_both_databases(research_database, vapid):
    store = Store(research_database)
    store.migrate()
    subscribe(store)
    assert push_alerts.find(store, ENDPOINT)["endpoint"] == ENDPOINT
    result = push_alerts.dispatch(store, events=[event("f" * 32, "Nvidia roadmap")], send=lambda row, message: 201)
    assert result["push_sent"] == 1
    assert push_alerts.remove(store, ENDPOINT) and push_alerts.count(store) == 0
    store.engine.dispose()


def test_site_keeps_working_when_the_crypto_package_is_missing(vapid, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives", None)
    assert push_alerts.vapid_key() is None and push_alerts.dispatch(object()) == {"push_status": "disabled"}
