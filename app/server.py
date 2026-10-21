"""FastAPI entry point detected by Vercel; no database or scraping on import."""
import hashlib
import hmac
import json
import logging
import os
import smtplib
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from app.news import collect_news
from app.web_digest import build_digest
from app.services.email import send_email

app = FastAPI(title="AI Brief", version="1.0.0", docs_url="/api/docs", redoc_url=None)
PUBLIC = Path(__file__).resolve().parent.parent / "public"
logger = logging.getLogger(__name__)
_limits = OrderedDict()
_limit_lock = threading.Lock()
_generation_lock = threading.Lock()
_digest_cache = OrderedDict()
_mail_history = OrderedDict()


class TimeWindow(IntEnum):
    day = 24
    week = 168
    month = 720


class DigestRequest(BaseModel):
    name: str = Field(default="Reader", min_length=1, max_length=60)
    focus: str = Field(default="AI engineering, agents, research, and practical applications", max_length=400)
    hours: Literal[24, 168, 720] = 168
    top_n: int = Field(default=5, ge=1, le=5)
    sources: list[Literal["openai", "anthropic", "youtube"]] = Field(default=["openai", "anthropic", "youtube"], min_length=1, max_length=3)


class EmailRequest(BaseModel):
    digest: dict
    signature: str = Field(max_length=128)
    expires: int


def rate_limit(request: Request, action: str, limit: int, window: int = 600):
    # This bounds requests per warm function instance; it is not a distributed quota.
    address = request.client.host if request.client else "unknown"
    if os.getenv("VERCEL"):
        address = request.headers.get("x-vercel-forwarded-for", address).split(",")[0].strip()
    key = (hashlib.sha256(address.encode()).hexdigest(), action)
    now = time.monotonic()
    with _limit_lock:
        history = _limits.setdefault(key, deque())
        while history and history[0] <= now - window:
            history.popleft()
        if len(history) >= limit:
            raise HTTPException(429, "Please wait a few minutes before trying again.", headers={"Retry-After": str(window)})
        history.append(now)
        _limits.move_to_end(key)
        while len(_limits) > 2000:
            _limits.popitem(last=False)


def signature(digest: dict, expires: int) -> str:
    secret = os.getenv("ADMIN_TOKEN", "")
    if not secret:
        return ""
    message = json.dumps({"digest": digest, "expires": expires}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def require_owner(authorization: str | None):
    secret = os.getenv("ADMIN_TOKEN", "")
    if not secret or not authorization or not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(401, "Enter the owner access key to send to the configured Gmail inbox.")


@app.middleware("http")
async def response_headers(request: Request, call_next):
    if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > 100000:
        return JSONResponse({"detail": "Request is too large."}, status_code=413)
    if request.method == "POST" and request.headers.get("origin"):
        from urllib.parse import urlparse
        if urlparse(request.headers["origin"]).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "email_configured": all(os.getenv(k) for k in ("MY_EMAIL", "APP_PASSWORD", "ADMIN_TOKEN"))}


@app.get("/api/news")
def news(hours: TimeWindow = TimeWindow.week, source: Literal["all", "openai", "anthropic", "youtube"] = "all", q: Annotated[str, Query(max_length=150)] = ""):
    payload = collect_news()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = [a for a in payload["articles"] if datetime.fromisoformat(a["published_at"]) >= cutoff
                and (source == "all" or a["source"] == source)
                and (not q or q.lower() in (a["title"] + " " + a["description"]).lower())]
    return dict(payload, articles=articles, total=len(articles))


@app.post("/api/digest")
def generate(body: DigestRequest, request: Request):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "AI generation is not configured yet.")
    rate_limit(request, "generate", 3)
    payload = news(hours=body.hours)
    available = [a for a in payload["articles"] if a["source"] in body.sources]
    # Round-robin sources so one busy feed does not crowd out the others.
    buckets = [[a for a in available if a["source"] == source] for source in dict.fromkeys(body.sources)]
    selected = []
    while len(selected) < body.top_n and any(buckets):
        for bucket in buckets:
            if bucket and len(selected) < body.top_n:
                selected.append(bucket.pop(0))
    if not selected:
        raise HTTPException(404, "No articles in this window. Try the past 30 days or another source.")
    cache_key = hashlib.sha256(json.dumps([body.model_dump(), [a["id"] for a in selected]], sort_keys=True).encode()).hexdigest()
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(429, "A digest is being prepared. Please try again in a moment.")
    try:
        cached = _digest_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 600:
            digest = cached[1]
        else:
            digest = build_digest(selected, body.name.strip() or "Reader", body.focus)
            _digest_cache[cache_key] = (time.monotonic(), digest)
            while len(_digest_cache) > 24:
                _digest_cache.popitem(last=False)
        expires = int(time.time()) + 3600
        return {"digest": digest, "expires": expires, "signature": signature(digest, expires),
                "source_basis": "Summaries use publisher RSS titles and excerpts, not full article text."}
    except (ValueError, RuntimeError):
        raise HTTPException(502, "The AI provider could not complete this digest. Please try again shortly.") from None
    finally:
        _generation_lock.release()


@app.post("/api/email")
def email(body: EmailRequest, request: Request, authorization: str | None = Header(default=None)):
    require_owner(authorization)
    rate_limit(request, "email", 2)
    if body.expires < time.time() or not hmac.compare_digest(body.signature, signature(body.digest, body.expires)):
        raise HTTPException(400, "This preview has expired or changed. Generate a new digest first.")
    if not all(os.getenv(k) for k in ("MY_EMAIL", "APP_PASSWORD")):
        raise HTTPException(503, "Gmail is not configured. Add MY_EMAIL and APP_PASSWORD in the server settings.")
    with _limit_lock:
        if body.signature in _mail_history:
            raise HTTPException(409, "This digest has already been sent.")
        _mail_history[body.signature] = time.time()
        while len(_mail_history) > 500:
            _mail_history.popitem(last=False)
    try:
        send_email("Your AI Brief", body.digest["markdown"], body.digest["html"], recipients=[os.environ["MY_EMAIL"]])
    except (smtplib.SMTPException, OSError, ValueError, KeyError):
        with _limit_lock:
            _mail_history.pop(body.signature, None)
        raise HTTPException(502, "Gmail could not send this digest. Check the saved Gmail app password and try again.") from None
    return {"success": True, "message": "Digest sent to the owner's configured Gmail inbox."}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(PUBLIC / "index.html")


# Vercel serves public/ from its CDN and omits it from the Python bundle.
if PUBLIC.is_dir():
    app.mount("/", StaticFiles(directory=PUBLIC), name="public")
