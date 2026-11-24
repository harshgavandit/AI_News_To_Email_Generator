"""Opt-in Web Push alerts for the stories, technologies and companies a reader follows.

Nothing is sent unless the owner sets ``NEWS_PUSH_VAPID_PRIVATE_KEY`` (see docs/PUSH-ALERTS.md).
A subscription holds the push service address, its public encryption keys and the reader's follow
list; no name or email address. Payloads are encrypted for the reader's browser (RFC 8291) and
signed with the site's VAPID key (RFC 8292), so push services cannot read them.
"""
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
import struct
import time
from urllib.parse import urlsplit
import zoneinfo

import httpx
from sqlalchemy import Column, Float, Integer, String, Table, Text, delete, inspect, select, update

from app.launch_store import schema

logger = logging.getLogger(__name__)

push_subscriptions = Table("brief_push_subscriptions", schema,
    Column("id", String(64), primary_key=True),  # SHA-256 of the endpoint
    Column("endpoint", Text, nullable=False),
    Column("p256dh", String(120), nullable=False), Column("auth", String(40), nullable=False),
    Column("profile", Text, nullable=False), Column("settings", Text, nullable=False),
    Column("seen", Text, nullable=False, default="{}"),
    Column("created", Float, nullable=False), Column("updated", Float, nullable=False),
    Column("checked", Float, nullable=False, default=0), Column("last_sent", Float, nullable=False, default=0),
    Column("sent_day", String(10), nullable=False, default=""), Column("sent_count", Integer, nullable=False, default=0),
    Column("failures", Integer, nullable=False, default=0))

# Browsers only hand out endpoints on these push services. Anything else is refused, so the
# server never posts to an address a visitor chose.
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com",
              "push.apple.com", "notify.windows.com")
MAX_SUBSCRIPTIONS_PER_RUN = 1000
MIN_GAP_SECONDS = 3 * 3600
SEEN_DAYS = 14
QUIET_START, QUIET_END = 22, 7  # local hours
MAX_FAILURES = 5
TTL_SECONDS = 12 * 3600


def b64(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def endpoint_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def valid_endpoint(endpoint: str) -> bool:
    if not isinstance(endpoint, str) or not 20 <= len(endpoint) <= 1024:
        return False
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return (parts.scheme == "https" and parts.port in {None, 443} and not parts.username and not parts.password
            and any(host == allowed or host.endswith("." + allowed) for allowed in PUSH_HOSTS))


def valid_keys(p256dh: str, auth: str) -> bool:
    try:
        public, secret = unb64(p256dh), unb64(auth)
    except (ValueError, TypeError):
        return False
    return len(public) == 65 and public[0] == 4 and len(secret) == 16


# --- VAPID (RFC 8292) -----------------------------------------------------------------------

def _crypto():
    # Imported on use, so the rest of the site keeps working if the package is missing locally.
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return hashes, serialization, ec, decode_dss_signature, AESGCM, HKDF


def vapid_key():
    raw = os.getenv("NEWS_PUSH_VAPID_PRIVATE_KEY", "").strip()
    if not raw:
        return None
    try:
        _, _, ec, *_ = _crypto()
    except ImportError:
        logger.error("push_crypto_unavailable: install the locked dependencies (uv sync)")
        return None
    try:
        secret = unb64(raw)
        if len(secret) != 32:
            raise ValueError("expected 32 bytes")
        return ec.derive_private_key(int.from_bytes(secret, "big"), ec.SECP256R1())
    except (ValueError, TypeError) as error:
        logger.error("push_vapid_key_invalid error_type=%s", type(error).__name__)
        return None


def public_key(key) -> str:
    _, serialization, *_ = _crypto()
    return b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))


def enabled() -> bool:
    return vapid_key() is not None


def vapid_subject() -> str:
    subject = os.getenv("NEWS_PUSH_SUBJECT", "").strip() or os.getenv("PUBLIC_ORIGIN", "").strip() or "https://getinformdaily.com"
    return subject if subject.startswith(("mailto:", "https://")) else "https://getinformdaily.com"


def vapid_authorization(endpoint: str, key, now: float | None = None) -> str:
    hashes, _, ec, decode_dss_signature, *_ = _crypto()
    parts = urlsplit(endpoint)
    header = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64(json.dumps({"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600),
                             "sub": vapid_subject()}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    token = f"{header}.{claims}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={public_key(key)}"


# --- Payload encryption (RFC 8291, aes128gcm) ----------------------------------------------

def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None, server_key=None) -> bytes:
    hashes, serialization, ec, _, AESGCM, HKDF = _crypto()
    receiver = unb64(p256dh)
    secret = unb64(auth)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    server_public = server_key.public_key().public_bytes(serialization.Encoding.X962,
                                                         serialization.PublicFormat.UncompressedPoint)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver))
    ikm = HKDF(hashes.SHA256(), 32, salt=secret, info=b"WebPush: info\x00" + receiver + server_public).derive(shared)
    salt = salt or os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!I", 4096) + bytes([len(server_public)]) + server_public + body


def deliver(row, message: dict, *, key=None, client=None) -> int:
    """POST one encrypted notification. Returns the push service's HTTP status (0 on network error)."""
    key = key or vapid_key()
    if key is None:
        return 0
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode()[:3000]
    headers = {"Authorization": vapid_authorization(row["endpoint"], key), "TTL": str(TTL_SECONDS),
               "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "Urgency": "normal"}
    if message.get("tag"):
        headers["Topic"] = hashlib.sha256(message["tag"].encode()).hexdigest()[:32]
    try:
        sender = client or httpx
        response = sender.post(row["endpoint"], content=encrypt(payload, row["p256dh"], row["auth"]),
                               headers=headers, timeout=6.0, follow_redirects=False)
        return response.status_code
    except httpx.HTTPError as error:
        logger.warning("push_delivery_failed error_type=%s", type(error).__name__)
        return 0


# --- Storage ---------------------------------------------------------------------------------

def ensure(store):
    if getattr(store, "_push_ready", False):
        return
    with store.engine.begin() as conn:
        if not inspect(conn).has_table(push_subscriptions.name):
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
            push_subscriptions.create(conn, checkfirst=True)
    store._push_ready = True


def save(store, endpoint, p256dh, auth, profile: dict, settings: dict, *, now=None):
    ensure(store)
    now = now or time.time()
    ident = endpoint_id(endpoint)
    values = {"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "profile": json.dumps(profile, sort_keys=True),
              "settings": json.dumps(settings, sort_keys=True), "updated": now, "failures": 0}
    with store.engine.begin() as conn:
        found = conn.execute(select(push_subscriptions.c.id).where(push_subscriptions.c.id == ident)).first()
        if found:
            conn.execute(update(push_subscriptions).where(push_subscriptions.c.id == ident).values(**values))
        else:
            # Start from now: older coverage is not news to someone who just turned alerts on.
            conn.execute(push_subscriptions.insert().values(id=ident, created=now, seen=json.dumps({"_since": now}),
                                                            checked=0, last_sent=0, sent_day="", sent_count=0, **values))
    return ident


def remove(store, endpoint) -> bool:
    ensure(store)
    with store.engine.begin() as conn:
        return conn.execute(delete(push_subscriptions).where(push_subscriptions.c.id == endpoint_id(endpoint))).rowcount > 0


def find(store, endpoint):
    ensure(store)
    with store.engine.connect() as conn:
        row = conn.execute(select(push_subscriptions).where(push_subscriptions.c.id == endpoint_id(endpoint))).mappings().first()
    return dict(row) if row else None


def rotate(store, old_endpoint, endpoint, p256dh, auth) -> bool:
    """A browser replaced its push address; keep the reader's follows and history."""
    row = find(store, old_endpoint)
    if not row:
        return False
    with store.engine.begin() as conn:
        conn.execute(delete(push_subscriptions).where(push_subscriptions.c.id == row["id"]))
        conn.execute(delete(push_subscriptions).where(push_subscriptions.c.id == endpoint_id(endpoint)))
        conn.execute(push_subscriptions.insert().values({**row, "id": endpoint_id(endpoint), "endpoint": endpoint,
                                                          "p256dh": p256dh, "auth": auth, "updated": time.time()}))
    return True


def count(store) -> int:
    ensure(store)
    with store.engine.connect() as conn:
        return len(conn.execute(select(push_subscriptions.c.id)).all())


# --- Selection and dispatch ------------------------------------------------------------------

def local_moment(settings, now):
    try:
        tz = zoneinfo.ZoneInfo(settings.get("timezone") or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        tz = UTC
    return datetime.fromtimestamp(now, UTC).astimezone(tz)


def quiet(settings, moment) -> bool:
    return bool(settings.get("quiet_hours", True)) and (moment.hour >= QUIET_START or moment.hour < QUIET_END)


def notification(picks):
    first = picks[0]
    reason = (first.get("reasons") or ["Update on something you follow"])[0]
    sources = first.get("source_count") or 1
    tag = f"informa-{first['id']}"
    if len(picks) == 1:
        return {"title": first["title"][:140], "body": f"{reason} · {sources} source{'s' if sources != 1 else ''}"[:220],
                "url": f"/development.html?id={first['id']}", "tag": tag}
    return {"title": f"{len(picks)} updates on what you follow",
            "body": f"{first['title'][:140]} — and {len(picks) - 1} more"[:220],
            "url": f"/development.html?id={first['id']}", "tag": tag}


def due(row, settings, now):
    moment = local_moment(settings, now)
    day = moment.date().isoformat()
    sent_today = row["sent_count"] if row["sent_day"] == day else 0
    limit = int(settings.get("max_per_day", 3))
    if sent_today >= limit or now - (row["last_sent"] or 0) < MIN_GAP_SECONDS or quiet(settings, moment):
        return None
    return day, sent_today


def select_updates(row, events, now):
    from app import ai_insights
    profile = ai_insights.RadarProfile.model_validate({**json.loads(row["profile"]), "length": 3})
    seen_raw = json.loads(row["seen"] or "{}")
    since = float(seen_raw.get("_since", 0))
    seen = {ident: value[0] for ident, value in seen_raw.items() if ident != "_since" and isinstance(value, list)}
    fresh = [event for event in events if datetime.fromisoformat(event["updated_at"]).timestamp() > since]
    return ai_insights.rank_events(fresh, profile, seen, followed_only=True), seen_raw


def mark_seen(seen_raw, picks, now):
    cutoff = now - SEEN_DAYS * 86400
    kept = {ident: value for ident, value in seen_raw.items()
            if ident == "_since" or (isinstance(value, list) and len(value) == 2 and value[1] >= cutoff)}
    for event in picks:
        kept[event["id"]] = [event["digest_version"], now]
    return kept


def dispatch(store, *, now=None, budget_seconds=20.0, events=None, send=None):
    """Send at most one notification per reader per run. Called after the hourly intelligence check."""
    key = vapid_key()
    if key is None:
        return {"push_status": "disabled"}
    ensure(store)
    started = time.monotonic()
    now = now or time.time()
    send = send or (lambda row, message: deliver(row, message, key=key))
    with store.engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(select(push_subscriptions).where(push_subscriptions.c.failures < MAX_FAILURES)
                                                   .order_by(push_subscriptions.c.checked).limit(MAX_SUBSCRIPTIONS_PER_RUN)).mappings()]
    result = {"push_status": "checked", "push_checked": 0, "push_sent": 0, "push_removed": 0}
    if not rows:
        return result
    for row in rows:
        if time.monotonic() - started > budget_seconds:
            result["push_status"] = "partial"
            break
        result["push_checked"] += 1
        values = {"checked": now}
        try:
            settings = json.loads(row["settings"] or "{}")
            window = due(row, settings, now)
            if window:
                if events is None:
                    from app import event_intelligence
                    events = event_intelligence.catalog(store, hours=24, limit=240)
                picks, seen_raw = select_updates(row, events, now)
                if picks:
                    status = send(row, notification(picks))
                    if status in {404, 410}:
                        with store.engine.begin() as conn:
                            conn.execute(delete(push_subscriptions).where(push_subscriptions.c.id == row["id"]))
                        result["push_removed"] += 1
                        continue
                    if 200 <= status < 300:
                        day, sent_today = window
                        values.update(seen=json.dumps(mark_seen(seen_raw, picks, now)), last_sent=now, sent_day=day,
                                      sent_count=sent_today + 1, failures=0)
                        result["push_sent"] += 1
                    else:
                        values["failures"] = row["failures"] + 1
        except (ValueError, TypeError, KeyError) as error:
            logger.warning("push_subscription_skipped error_type=%s", type(error).__name__)
            values["failures"] = row["failures"] + 1
        with store.engine.begin() as conn:
            conn.execute(update(push_subscriptions).where(push_subscriptions.c.id == row["id"]).values(**values))
    with store.engine.begin() as conn:
        result["push_removed"] += conn.execute(delete(push_subscriptions).where(
            push_subscriptions.c.failures >= MAX_FAILURES)).rowcount
    return result
