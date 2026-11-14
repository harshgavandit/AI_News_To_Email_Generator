"""Verify Resend delivery events before suppressing bounced or complaining inboxes."""
import base64
import binascii
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app import public_mail
from app.launch_store import get_store

router = APIRouter(prefix="/api/mail/events")


def valid_signature(body: bytes, headers, secret: str) -> bool:
    ident, timestamp = headers.get("svix-id", ""), headers.get("svix-timestamp", "")
    if not ident or len(ident) > 150 or not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12:
        return False
    if abs(time.time() - int(timestamp)) > 300 or not secret.startswith("whsec_"):
        return False
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, binascii.Error):
        return False
    if not key:
        return False
    signature = base64.b64encode(hmac.digest(key, f"{ident}.{timestamp}.".encode() + body, "sha256")).decode()
    return any(hmac.compare_digest(item.encode(), f"v1,{signature}".encode())
               for item in headers.get("svix-signature", "")[:4096].split())


def record_event(ident, kind, addresses):
    store = get_store()
    if not store or len(os.getenv("MAIL_SESSION_SECRET", "")) < 32:
        raise HTTPException(503, "Mail event storage is temporarily unavailable.")
    keys = set()
    for value in addresses[:50]:
        if not isinstance(value, str) or len(value) > 254:
            continue
        try:
            email = public_mail.normalize(value)
        except HTTPException:
            continue
        keys.add(public_mail.digest_key("mailbox:" + email))
    store.record_mail_event(hashlib.sha256(ident.encode()).hexdigest(), kind, keys)


@router.post("/resend")
async def resend_event(request: Request):
    secret = os.getenv("RESEND_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "Mail event processing is not configured.")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 64_000:
            raise HTTPException(413, "Mail event too large.")
    if not valid_signature(raw, request.headers, secret):
        raise HTTPException(401, "Invalid mail event signature.")
    try:
        event = json.loads(raw)
        kind, data = event["type"], event["data"]
        addresses = data.get("to", [])
        if not isinstance(addresses, list):
            raise TypeError
    except (KeyError, ValueError, TypeError, AttributeError, UnicodeError):
        raise HTTPException(400, "Invalid mail event.") from None
    suppressed = kind in ("email.bounced", "email.complained", "email.suppressed")
    if suppressed or kind in ("email.delivered", "email.delivery_delayed", "email.failed"):
        await run_in_threadpool(record_event, request.headers["svix-id"], kind, addresses if suppressed else [])
    return {"received": True}
