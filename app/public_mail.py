"""On-demand digest delivery to a verified mailbox with optional morning subscription."""
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
import zoneinfo

import httpx
from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from email_validator import EmailNotValidError, validate_email

from app.brand import BRIEF_SUBJECT, NAME, PUBLIC_SITE, VERIFICATION_SUBJECT
from app.launch_store import get_store
from app.mail_capacity import mail_capacity

router = APIRouter(prefix="/api/mail")
SESSION = "brief_mail"
CHALLENGE = "brief_challenge"
CODE_TTL = 600
SESSION_TTL = 7 * 86400


def has_transport():
    sender = os.getenv("MAIL_FROM") or os.getenv("MY_EMAIL")
    transactional = sender and (os.getenv("RESEND_API_KEY") or os.getenv("POSTMARK_SERVER_TOKEN"))
    smtp = os.getenv("SMTP_URL") or (os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASS"))
    return bool(transactional or smtp or (os.getenv("MY_EMAIL") and os.getenv("APP_PASSWORD")))


def ready():
    return (
        os.getenv("PUBLIC_EMAIL_ENABLED") == "1"
        and len(os.getenv("MAIL_SESSION_SECRET", "")) >= 32
        and has_transport()
        and all(os.getenv(key) for key in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY", "PUBLIC_ORIGIN"))
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
    if not token or len(token) > 2048:
        return None
    try:
        encoded, proof = token.split(".", 1)
        if not hmac.compare_digest(digest_key(purpose + ":" + encoded), proof):
            return None
        expiry, payload = json.loads(base64.urlsafe_b64decode(encoded))
        return payload if expiry > time.time() else None
    except (ValueError, TypeError):
        return None


def cookie(response, key, purpose, payload, ttl):
    response.set_cookie(
        key,
        seal(purpose, payload, ttl),
        max_age=ttl,
        httponly=True,
        secure=bool(os.getenv("VERCEL")) or os.getenv("PUBLIC_ORIGIN", "").startswith("https://"),
        samesite="strict",
        path="/api/mail",
    )


def is_pilot_address(email):
    my_email = os.getenv("MY_EMAIL")
    if os.getenv("MAIL_PILOT_MODE") != "1" or not my_email:
        return True
    return email == normalize(my_email)


def address_key(request):
    client = request.client.host if request.client else "unknown"
    if os.getenv("VERCEL"):
        client = request.headers.get("x-vercel-forwarded-for", client).split(",")[0].strip()
    return digest_key("ip:" + client)


def session_email(token):
    payload = unseal("session", token)
    return payload.get("email") if isinstance(payload, dict) else payload


def session_recipient(request: Request, store=None):
    if len(os.getenv("MAIL_SESSION_SECRET", "")) < 32:
        return None
    token = request.cookies.get(SESSION)
    recipient = session_email(token)
    if not isinstance(recipient, str):
        return None
    store = store or get_store()
    return recipient if store and not store.mail_session_revoked(digest_key("session-token:" + token)) else None


def verified_recipient(request: Request):
    recipient = session_recipient(request)
    return recipient if isinstance(recipient, str) and is_pilot_address(recipient) else None


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
    origin_host = urlsplit(os.environ["PUBLIC_ORIGIN"]).hostname
    allowed_hosts = {origin_host}
    allowed_hosts.update(os.getenv("TURNSTILE_ALLOWED_HOSTNAMES", "").lower().replace(",", " ").split())
    hostname = request.url.hostname
    if hostname not in allowed_hosts:
        return False
    try:
        response = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": os.environ["TURNSTILE_SECRET_KEY"], "response": token},
            timeout=7,
        )
        response.raise_for_status()
        result = response.json()
        return (
            result.get("success") is True
            and result.get("action") == "verify_email"
            and result.get("hostname") == hostname
        )
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "The bot check is temporarily unavailable.") from None


def send_message(recipient, subject, body, html, key, unsubscribe_url=None, **kwargs):
    # Resend deduplicates this exact payload and key, including after a lost response.
    attempts = 2 if os.getenv("RESEND_API_KEY") else 1
    for attempt in range(attempts):
        try:
            return send_via_transport(recipient, subject, body, html, key, unsubscribe_url)
        except httpx.HTTPError as error:
            transient = isinstance(error, httpx.RequestError) or (
                isinstance(error, httpx.HTTPStatusError) and error.response.status_code >= 500)
            if transient and attempt + 1 < attempts:
                continue
            raise OSError("Mail transport did not confirm acceptance") from None
        except ValueError:
            # HTTP exceptions and invalid provider responses can contain private data.
            raise OSError("Mail transport did not confirm acceptance") from None


def send_via_transport(recipient, subject, body, html, key, unsubscribe_url):
    # 1. Resend API
    if os.getenv("RESEND_API_KEY"):
        sender = os.getenv("MAIL_FROM") or os.getenv("MY_EMAIL") or f"brief@{urlsplit(PUBLIC_SITE).hostname}"
        email_headers = {}
        if unsubscribe_url:
            email_headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            email_headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        payload = {
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "text": body,
            "html": html,
            "headers": email_headers,
        }
        if not html:
            payload.pop("html")
        resp = httpx.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Idempotency-Key": key},
            timeout=15,
        )
        resp.raise_for_status()
        provider_id = resp.json().get("id")
        if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 160:
            raise ValueError("Missing provider acceptance")
        return provider_id

    # 2. Postmark API
    if os.getenv("POSTMARK_SERVER_TOKEN"):
        sender = os.getenv("MAIL_FROM") or os.getenv("MY_EMAIL")
        postmark_headers = []
        if unsubscribe_url:
            postmark_headers.append({"Name": "List-Unsubscribe", "Value": f"<{unsubscribe_url}>"})
            postmark_headers.append({"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"})
        payload = {
            "From": sender,
            "To": recipient,
            "Subject": subject,
            "TextBody": body,
            "HtmlBody": html,
            "Headers": postmark_headers,
        }
        if not html:
            payload.pop("HtmlBody")
        resp = httpx.post(
            "https://api.postmarkapp.com/email",
            json=payload,
            headers={"X-Postmark-Server-Token": os.environ["POSTMARK_SERVER_TOKEN"], "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        provider_id = result.get("MessageID")
        if result.get("ErrorCode", 0) or not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 160:
            raise ValueError("Missing provider acceptance")
        return provider_id

    # 3. SMTP URL
    smtp_url = os.getenv("SMTP_URL")
    if not smtp_url and all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS")):
        from urllib.parse import quote
        host = os.environ["SMTP_HOST"]
        port = int(os.getenv("SMTP_PORT", "587"))
        username = quote(os.environ["SMTP_USER"], safe="")
        password = quote(os.environ["SMTP_PASS"], safe="")
        scheme = "smtps" if port == 465 else "smtp"
        smtp_url = f"{scheme}://{username}:{password}@{host}:{port}"
    if smtp_url:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(smtp_url)
        if parsed.scheme not in {"smtp", "smtps"} or not parsed.hostname:
            raise ValueError("Invalid SMTP configuration")
        sender = os.getenv("MAIL_FROM") or (unquote(parsed.username) if parsed.username else
                                           f"brief@{urlsplit(PUBLIC_SITE).hostname}")
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg["Message-ID"] = f"<{key}@{urlsplit(PUBLIC_SITE).hostname}>"
        if unsubscribe_url:
            msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
        port = parsed.port or (465 if parsed.scheme == "smtps" else 587)
        if parsed.scheme == "smtps":
            with smtplib.SMTP_SSL(parsed.hostname, port, timeout=15, context=ssl.create_default_context()) as smtp:
                if parsed.username and parsed.password:
                    smtp.login(unquote(parsed.username), unquote(parsed.password))
                refused = smtp.send_message(msg)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
        else:
            with smtplib.SMTP(parsed.hostname, port, timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if parsed.username and parsed.password:
                    smtp.login(unquote(parsed.username), unquote(parsed.password))
                refused = smtp.send_message(msg)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
        return key

    # 4. Gmail SMTP Fallback
    sender = os.environ["MY_EMAIL"]
    password = "".join(os.environ["APP_PASSWORD"].split())
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{key}@{urlsplit(PUBLIC_SITE).hostname}>"
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15, context=ssl.create_default_context()) as smtp:
        smtp.login(sender, password)
        refused = smtp.send_message(msg)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
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
    email: str | None = Field(default=None, max_length=254)
    subscribe: bool = False
    timezone: str | None = Field(default=None, max_length=64)


@router.get("/config")
def config(request: Request, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    enabled = ready() and bool(os.getenv("NEWS_DATABASE_URL"))
    email = verified_recipient(request) if enabled else None
    store = get_store() if email else None
    remaining = max(0, 3 - store.mail_used(digest_key("mailbox:" + email), day())) if store else None
    return {
        "enabled": enabled,
        "pilot": enabled and os.getenv("MAIL_PILOT_MODE") == "1",
        "site_key": os.getenv("TURNSTILE_SITE_KEY") if enabled else None,
        "verified": bool(email),
        "verified_email": email,
        "limit": 3,
        "timezone": "UTC",
        "remaining_today": remaining,
        "delivery_tracking": bool(os.getenv("RESEND_API_KEY") and os.getenv("RESEND_WEBHOOK_SECRET")),
    }


@router.get("/delivery/{preview_id}")
def delivery_receipt(request: Request, response: Response,
                     preview_id: str = Path(pattern=r"^[A-Za-z0-9_-]{24,80}$")):
    store = required_store()
    response.headers["Cache-Control"] = "private, no-store"
    recipient = verified_recipient(request)
    if not recipient:
        raise HTTPException(401, "Verify your inbox to check this delivery.")
    mailbox = digest_key("mailbox:" + recipient)
    receipt = store.delivery_status(digest_key(f"delivery:{mailbox}:{preview_id}"))
    if not receipt:
        raise HTTPException(404, "No delivery attempt for this brief and verified inbox.")
    return {**receipt, "remaining_today": max(0, 3 - store.mail_used(mailbox, day())),
            "limit": 3, "timezone": "UTC",
            "tracking": bool(os.getenv("RESEND_API_KEY") and os.getenv("RESEND_WEBHOOK_SECRET"))}


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
    if store.suppressed(mailbox):
        raise HTTPException(422, "Use a different inbox for verification.")
    if not store.admit([
        (f"code:{mailbox}", str(int(time.time()) // 60), 1),
        (f"code-day:{mailbox}", day(), 3),
        (f"code-ip:{ip}", day(), 8),
        *mail_capacity().policies(day(), "verification"),
    ]):
        raise limited("Verification is limited. Wait a minute or try again tomorrow.")
    ident, code = secrets.token_urlsafe(24), f"{secrets.randbelow(1_000_000):06d}"
    store.save_code(ident, mailbox, digest_key(f"code:{ident}:{code}"), time.time() + CODE_TTL)
    try:
        send_message(email, VERIFICATION_SUBJECT, f"This code expires in 10 minutes. Your code is {code}.", None, ident)
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
            cookie(response, SESSION, "session", {"email": email, "nonce": secrets.token_urlsafe(16)}, SESSION_TTL)
            return {"verified": True, "email": email}
    raise HTTPException(400, "That code is invalid or expired. Request a new code.")


@router.post("/logout")
def logout(request: Request, response: Response):
    if len(os.getenv("MAIL_SESSION_SECRET", "")) >= 32:
        token = request.cookies.get(SESSION)
        pending = unseal("challenge", request.cookies.get(CHALLENGE))
        recipient = session_email(token)
        if recipient or pending:
            store = get_store()
            if not store:
                raise HTTPException(503, "Mail sign-out is temporarily unavailable. Try again shortly.")
            if recipient:
                store.revoke_mail_session(digest_key("session-token:" + token), time.time() + SESSION_TTL)
            if pending:
                ident, email = pending
                store.discard_code(ident, digest_key("mailbox:" + email))
    for name in (SESSION, CHALLENGE):
        response.delete_cookie(name, path="/api/mail")
    return {"verified": False}


@router.post("/send")
def send(body: SendBody, request: Request):
    store = required_store()
    recipient = session_recipient(request, store)
    if recipient and not is_pilot_address(recipient):
        raise HTTPException(403, "Email delivery is in a limited test.")
    if not recipient:
        raise HTTPException(401, "Verify your inbox before sending a brief.")
    if body.email is not None:
        if normalize(body.email) != recipient:
            raise HTTPException(422, "Email address does not match your verified inbox.")
    if body.subscribe:
        if not body.timezone or body.timezone not in zoneinfo.available_timezones():
            raise HTTPException(422, "Provide a valid IANA timezone to enable scheduled delivery.")
    payload = store.get_preview(body.preview_id)
    if not payload:
        raise HTTPException(404, "This preview expired. Generate a new brief.")
    mailbox = digest_key("mailbox:" + recipient)
    if store.suppressed(mailbox):
        raise HTTPException(422, "Use a different verified inbox for delivery.")
    identity = digest_key(f"delivery:{mailbox}:{body.preview_id}")
    ip = address_key(request)
    state, accepted = store.reserve_delivery(identity, [
        (f"mail:{mailbox}", day(), 3),
        *mail_capacity().policies(day(), "digests"),
    ], windows=[(f"dispatch-ip:{ip}", 3600, 5), (f"mailbox-hour:{mailbox}", 3600, 5)],
       event_mailbox=mailbox, event_history=payload.get("_catchup"))
    if state == "limited":
        if accepted is not None:
            raise HTTPException(429, "Delivery is limited to five requests per hour.",
                                headers={"Retry-After": str(accepted)})
        raise limited("This inbox or IP address has reached its hourly or daily sending limit. Please wait a bit before requesting another brief.")
    if accepted:
        res = {"status": "accepted", "message": "Your brief was accepted for delivery."}
        if body.subscribe:
            from app.mail_schedule import next_morning
            store.subscribe(mailbox, recipient, body.timezone, next_morning(body.timezone))
            res["subscribed"] = True
        return res
    if state != "new":
        raise HTTPException(409, "This brief already has a send attempt. Check your inbox before requesting another.")
    try:
        message_options = {}
        if body.subscribe:
            from app.mail_schedule import build_unsubscribe_url, with_unsubscribe
            message_options["unsubscribe_url"] = build_unsubscribe_url(mailbox)
            payload = with_unsubscribe(payload, message_options["unsubscribe_url"])
        provider_id = send_message(recipient, BRIEF_SUBJECT, payload["markdown"], payload["html"], identity, **message_options)
    except (OSError, smtplib.SMTPException):
        # Transport acceptance can be ambiguous after a timeout. Keep the reservation.
        raise HTTPException(502, "Delivery could not be confirmed. Check your inbox before trying another brief.") from None
    store.record_delivery(identity, provider_id)
    res = {"status": "accepted", "message": "Your brief was accepted for delivery."}
    if body.subscribe:
        from app.mail_schedule import next_morning
        store.subscribe(mailbox, recipient, body.timezone, next_morning(body.timezone))
        res["subscribed"] = True
    return res


@router.get("/unsubscribe/{token}")
def unsubscribe_confirm(token: str):
    mailbox = unseal("unsubscribe", token)
    if not mailbox:
        raise HTTPException(400, "That unsubscribe link is invalid or expired.")
    return Response(
        content=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Unsubscribe · {NAME}</title></head>
        <body style="font-family:-apple-system,sans-serif;max-width:500px;margin:60px auto;padding:24px;text-align:center;background:#f6f4ee;color:#252e29;">
        <h1 style="font-family:Georgia,serif;font-weight:normal;font-size:28px;">{NAME}</h1>
        <p style="color:#697169;font-size:14px;line-height:1.6;">Click below to confirm unsubscribing from automatic daily morning delivery.</p>
        <form method="POST">
        <input type="hidden" name="List-Unsubscribe" value="One-Click">
        <button type="submit" style="padding:12px 24px;font-size:13px;font-weight:600;background:#294a3b;color:white;border:none;border-radius:6px;cursor:pointer;">Unsubscribe My Inbox</button>
        </form></body></html>""",
        media_type="text/html",
    )


@router.post("/unsubscribe/{token}")
def unsubscribe_action(token: str):
    store = required_store()
    mailbox = unseal("unsubscribe", token)
    if not mailbox:
        raise HTTPException(400, "That unsubscribe link is invalid or expired.")
    store.unsubscribe(mailbox)
    return {"unsubscribed": True, "message": "You have been successfully unsubscribed from daily morning delivery."}
