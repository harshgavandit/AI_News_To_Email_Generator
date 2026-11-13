"""On-demand digest delivery to a verified mailbox; no subscriptions."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import time
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from email_validator import EmailNotValidError, validate_email

from app.launch_store import get_store

router = APIRouter(prefix="/api/mail")
SESSION = "brief_mail"
CHALLENGE = "brief_challenge"
CODE_TTL = 600
SESSION_TTL = 7 * 86400


def ready():
    return os.getenv("PUBLIC_EMAIL_ENABLED") == "1" and len(os.getenv("MAIL_SESSION_SECRET", "")) >= 32 and all(
        os.getenv(key) for key in ("MY_EMAIL", "APP_PASSWORD", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY", "PUBLIC_ORIGIN")
    )


def required_store():
    if ready():
        store = get_store()
        if store and (not os.getenv("VERCEL") or store.engine.dialect.name == "postgresql"):
            return store
    raise HTTPException(503, "Public email delivery is not available yet.")


def digest_key(value):
    return hmac.new(os.environ["MAIL_SESSION_SECRET"].encode(), value.encode(), hashlib.sha256).hexdigest()


def seal(purpose, payload, ttl):
    encoded = base64.urlsafe_b64encode(json.dumps([int(time.time()) + ttl, payload]).encode()).decode()
    return f"{encoded}.{digest_key(purpose + ':' + encoded)}"


def unseal(purpose, token):
    try:
        encoded, proof = (token or "").split(".", 1)
        if not hmac.compare_digest(digest_key(purpose + ':' + encoded), proof):
            return None
        expiry, payload = json.loads(base64.urlsafe_b64decode(encoded))
        return payload if expiry > time.time() else None
    except (ValueError, TypeError):
        return None


def cookie(response, key, purpose, payload, ttl):
    response.set_cookie(key, seal(purpose, payload, ttl), max_age=ttl, httponly=True,
                        secure=os.getenv("PUBLIC_ORIGIN", "").startswith("https://"), samesite="strict", path="/api/mail")


def is_pilot_address(email):
    return os.getenv("MAIL_PILOT_MODE") != "1" or email == normalize(os.environ["MY_EMAIL"])


def address_key(request):
    client = request.client.host if request.client else "unknown"
    if os.getenv("VERCEL"):
        client = request.headers.get("x-vercel-forwarded-for", client).split(",")[0].strip()
    return digest_key("ip:" + client)


def day():
    return datetime.now(UTC).date().isoformat()


def limited(message):
    now = datetime.now(UTC)
    next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return HTTPException(429, message, headers={"Retry-After": str(max(1, int((next_day - now).total_seconds())))})


def normalize(email):
    try:
        value = validate_email(email.strip(), check_deliverability=False, allow_smtputf8=False).normalized.casefold()
    except EmailNotValidError:
        raise HTTPException(422, "Enter a valid email address.") from None
    local, domain = value.rsplit("@", 1)
    if domain in {"gmail.com", "googlemail.com"}:
        local, domain = local.split("+", 1)[0].replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def verify_human(token, request):
    try:
        response = httpx.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                              data={"secret": os.environ["TURNSTILE_SECRET_KEY"], "response": token}, timeout=7)
        response.raise_for_status()
        result = response.json()
        return (result.get("success") is True and result.get("action") == "verify_email" and
                result.get("hostname") == urlsplit(os.environ["PUBLIC_ORIGIN"]).hostname)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "The bot check is temporarily unavailable.") from None


def send_message(recipient, subject, body, html, key):
    sender = os.environ["MY_EMAIL"]
    password = "".join(os.environ["APP_PASSWORD"].split())
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{key}@ai-news-to-email-generator.vercel.app>"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15, context=ssl.create_default_context()) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    return key


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChallengeBody(StrictBody):
    email: str = Field(min_length=3, max_length=254)
    captcha: str = Field(min_length=1, max_length=2048)


class VerifyBody(StrictBody):
    code: str = Field(pattern=r"^[0-9]{6}$")


class SendBody(StrictBody):
    preview_id: str = Field(pattern=r"^[A-Za-z0-9_-]{24,80}$")


@router.get("/config")
def config(request: Request):
    enabled = ready() and bool(os.getenv("NEWS_DATABASE_URL"))
    email = unseal("session", request.cookies.get(SESSION)) if enabled else None
    return {"enabled": enabled, "pilot": enabled and os.getenv("MAIL_PILOT_MODE") == "1",
            "site_key": os.getenv("TURNSTILE_SITE_KEY") if enabled else None,
            "verified": bool(email), "limit": 3, "timezone": "UTC"}


@router.post("/challenge")
def challenge(body: ChallengeBody, request: Request, response: Response):
    store = required_store()
    email = normalize(body.email)
    if not is_pilot_address(email):
        raise HTTPException(403, "Email delivery is in a limited test.")
    ip = address_key(request)
    if not store.admit([(f"captcha:{ip}", day(), 15)]):
        raise limited("Too many verification attempts today.")
    if not verify_human(body.captcha, request):
        raise HTTPException(400, "Complete the bot check and try again.")
    mailbox = digest_key("mailbox:" + email)
    # Keep verification and digest quotas separate, plus one shared outbound budget.
    if not store.admit([(f"code:{mailbox}", str(int(time.time()) // 60), 1),
                        (f"code-day:{mailbox}", day(), 3), (f"code-ip:{ip}", day(), 8),
                        ("outbound", day(), 60), ("verification", day(), 20)]):
        raise limited("Verification is limited. Wait a minute or try again tomorrow.")
    ident, code = secrets.token_urlsafe(24), f"{secrets.randbelow(1_000_000):06d}"
    store.save_code(ident, mailbox, digest_key(f"code:{ident}:{code}"), time.time() + CODE_TTL)
    try:
        send_message(email, "Your World Tech Brief verification code", f"This code expires in 10 minutes. Your code is {code}.", None, ident)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(502, "The verification message could not be sent right now.") from None
    cookie(response, CHALLENGE, "challenge", [ident, email], CODE_TTL)
    return {"status": "code_sent"}


@router.post("/verify")
def verify(body: VerifyBody, request: Request, response: Response):
    store = required_store()
    pending = unseal("challenge", request.cookies.get(CHALLENGE))
    if pending:
        ident, email = pending
        if store.consume_code(ident, digest_key("mailbox:" + email), digest_key(f"code:{ident}:{body.code}")):
            response.delete_cookie(CHALLENGE, path="/api/mail")
            cookie(response, SESSION, "session", email, SESSION_TTL)
            return {"verified": True}
    raise HTTPException(400, "That code is invalid or expired. Request a new code.")


@router.post("/logout")
def logout(response: Response):
    for name in (SESSION, CHALLENGE):
        response.delete_cookie(name, path="/api/mail")
    return {"verified": False}


@router.post("/send")
def send(body: SendBody, request: Request):
    store = required_store()
    recipient = unseal("session", request.cookies.get(SESSION))
    if recipient and not is_pilot_address(recipient):
        raise HTTPException(403, "Email delivery is in a limited test.")
    if not recipient:
        raise HTTPException(401, "Verify your inbox before sending a brief.")
    payload = store.get_preview(body.preview_id)
    if not payload:
        raise HTTPException(404, "This preview expired. Generate a new brief.")
    mailbox = digest_key("mailbox:" + recipient)
    identity = digest_key(f"delivery:{mailbox}:{body.preview_id}")
    state, accepted = store.reserve_delivery(identity, [(f"mail:{mailbox}", day(), 3),
                                                        ("outbound", day(), 60), ("digests", day(), 45)])
    if state == "limited":
        raise limited("This inbox or World Tech Brief has reached its daily sending limit. Try again after midnight UTC.")
    if accepted:
        return {"status": "accepted", "message": "Your brief was accepted for delivery."}
    if state != "new":
        raise HTTPException(409, "This brief already has a send attempt. Check your inbox before requesting another.")
    try:
        provider_id = send_message(recipient, "Your World Tech Brief", payload["markdown"], payload["html"], identity)
    except (OSError, smtplib.SMTPException):
        # SMTP acceptance can be ambiguous after a timeout. Keep the reservation.
        raise HTTPException(502, "Delivery could not be confirmed. Check your inbox before trying another brief.") from None
    store.record_delivery(identity, provider_id)
    return {"status": "accepted", "message": "Your brief was accepted for delivery."}
