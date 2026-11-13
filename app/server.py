"""FastAPI entry point detected by Vercel; no database or scraping on import."""
import hashlib
import hmac
import json
import logging
import os
import secrets
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
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

from app.news import collect_news
from app.coverage import TOPICS, public_article, topic_for
from app.web_digest import build_digest
from app.world_edition import build_world, select_world
from app.services.email import send_email
from app.ingestion import refresh_sources, source_catalog
from app.launch_store import decode_cursor, get_store, page_result
from app.public_mail import router as mail_router
from app.selection import select_candidates, words
from app.sources import BY_ID, GROUPS, KINDS

app = FastAPI(title="World Tech Brief", version="1.1.0", docs_url="/api/docs", redoc_url=None)
app.include_router(mail_router)
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
    edition: Literal["personal", "world"] = "personal"
    name: str = Field(default="Reader", min_length=1, max_length=60)
    focus: str = Field(default="AI engineering, agents, research, and practical applications", max_length=400)
    hours: Literal[24, 168, 720] = 168
    top_n: int = Field(default=5, ge=1, le=5)
    sources: list[str] = Field(default_factory=lambda: list(GROUPS), min_length=1, max_length=len(BY_ID))

    @field_validator("sources")
    @classmethod
    def known_sources(cls, values):
        if any(value not in GROUPS and value not in BY_ID for value in values):
            raise ValueError("Choose a supported source.")
        return list(dict.fromkeys(values))


class SourceUpdate(BaseModel):
    enabled: bool


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
    if request.method in {"POST", "PATCH"} and request.headers.get("origin"):
        from urllib.parse import urlparse
        if urlparse(request.headers["origin"]).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    try:
        response = await call_next(request)
    except SQLAlchemyError:
        logger.warning("Database request failed: %s", request.url.path)
        response = JSONResponse({"detail": "The news database is temporarily unavailable."}, status_code=503)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self' data:; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    if request.url.path == "/api/docs":
        # Swagger's standard template loads its UI assets from jsDelivr.
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "email_configured": all(os.getenv(k) for k in ("MY_EMAIL", "APP_PASSWORD", "ADMIN_TOKEN"))}


@app.get("/api/sources")
def sources():
    return {"sources": source_catalog(get_store()), "topics": TOPICS}


def source_store():
    store = get_store()
    if not store:
        raise HTTPException(503, "Source history is not configured.")
    return store


@app.post("/api/admin/sources")
def admin_sources(authorization: str | None = Header(default=None)):
    require_owner(authorization)
    return {"sources": source_catalog(source_store())}


@app.post("/api/admin/setup")
def initialize_news(authorization: str | None = Header(default=None)):
    require_owner(authorization)
    store = source_store()
    store.migrate()
    return {"database": store.engine.dialect.name, "schema_ready": True}


@app.patch("/api/admin/sources/{source_id}")
def update_source(source_id: str, body: SourceUpdate, authorization: str | None = Header(default=None)):
    require_owner(authorization)
    if source_id not in BY_ID:
        raise HTTPException(404, "Unknown source.")
    source_store().enable(source_id, body.enabled)
    return {"source": source_id, "enabled": body.enabled}


@app.get("/api/jobs/refresh")
def refresh_job(authorization: str | None = Header(default=None)):
    secrets_ = [os.getenv(name, "") for name in ("CRON_SECRET", "FEED_REFRESH_SECRET")]
    if not authorization or not any(len(secret) >= 16 and hmac.compare_digest(authorization, f"Bearer {secret}")
                                    for secret in secrets_):
        raise HTTPException(401, "Unauthorized.")
    store = source_store()
    # Each scheduled run claims its own time bucket before contacting publishers.
    if not store.admit([("feed-refresh", str(int(time.time()) // 300), 1)]):
        return {"status": "already_started"}
    catalog = refresh_sources(store)
    active = [s for s in catalog if s["enabled"]]
    healthy = sum(s["available"] is True for s in active)
    if active and not healthy:
        raise HTTPException(503, "All enabled feeds failed their latest check.")
    return {"status": "refreshed", "sources": len(active), "healthy": healthy}


@app.post("/api/admin/refresh")
def refresh_admin(source: str | None = None, authorization: str | None = Header(default=None)):
    require_owner(authorization)
    if source and source not in BY_ID:
        raise HTTPException(404, "Unknown source.")
    store = source_store()
    if not store.admit([("admin-refresh", str(int(time.time()) // 60), 1)]):
        raise HTTPException(429, "Wait a minute before refreshing again.")
    return {"sources": refresh_sources(store, source)}


@app.get("/api/news")
def news(hours: TimeWindow = TimeWindow.week, source: str = "all",
         q: Annotated[str, Query(max_length=150)] = "", kind: str = "all", publisher: str = "", topic: str = "all",
         limit: Annotated[int, Query(ge=1, le=50)] = 24, cursor: Annotated[str | None, Query(max_length=320)] = None):
    if (source not in ("all", *GROUPS) and source not in BY_ID) or kind not in KINDS or (publisher and publisher not in BY_ID):
        raise HTTPException(422, "Choose a supported source or content type.")
    if topic != "all" and topic not in TOPICS:
        raise HTTPException(422, "Choose a supported topic.")
    q = q.strip()
    store = get_store()
    try:
        if store:
            catalog = source_catalog(store)
            page = store.page(hours=hours, source=source, query=q, kind=kind, publisher=publisher, limit=limit, cursor=cursor, topic=topic)
            active = [s for s in catalog if s["enabled"]]
            return dict(page, articles=[public_article(a) for a in page["articles"]], sources=catalog,
                        fetched_at=max((s["checked_at"] or "" for s in active), default="") or None,
                        last_success=max((s["last_success"] or "" for s in active), default="") or None)
        payload = collect_news()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        articles = [a for a in payload["articles"] if datetime.fromisoformat(a["published_at"]) >= cutoff
                    and (source == "all" or source in (a["source"], a.get("source_id")))
                    and (kind == "all" or a.get("kind") == kind)
                    and (topic == "all" or topic_for(a) == topic)
                    and (not publisher or a.get("source_id") == publisher)
                    and (not q or q.lower() in (a["title"] + " " + a["description"]).lower())]
        fingerprint = hashlib.sha256(json.dumps([hours, source, q, kind, publisher, topic]).encode()).hexdigest()[:16]
        total = len(articles)
        articles.sort(key=lambda a: (a["published_at"], a["id"]), reverse=True)
        if cursor:
            after = tuple(decode_cursor(cursor, fingerprint))
            articles = [a for a in articles if (a["published_at"], a["id"]) < after]
        return {**payload, **page_result([public_article(a) for a in articles], total, limit, fingerprint)}
    except ValueError:
        raise HTTPException(400, "Invalid page cursor.") from None


@app.post("/api/digest")
def generate(body: DigestRequest, request: Request):
    world = body.edition == "world"
    if not world and not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "AI generation is not configured yet.")
    store = get_store()
    if store:
        address = request.client.host if request.client else "unknown"
        if os.getenv("VERCEL"):
            address = request.headers.get("x-vercel-forwarded-for", address).split(",")[0].strip()
        ident = hashlib.sha256(address.encode()).hexdigest()
        today = datetime.now(timezone.utc).date().isoformat()
        policies = ([(f"world:{ident}", str(int(time.time()) // 600), 30)] if world else
                    [(f"generate:{ident}", today, 8), ("generate-total", today, 60)])
        if not store.admit(policies):
            if world:
                raise HTTPException(429, "Too many brief requests. Please wait a few minutes.")
            raise HTTPException(429, "Digest generation has reached its daily limit. Try again after midnight UTC.")
        available = store.world_candidates(body.hours, body.sources) if world else store.candidates(body.hours, body.sources, words(body.focus))
    else:
        rate_limit(request, "world" if world else "generate", 15 if world else 3)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=body.hours)
        available = [a for a in collect_news()["articles"] if datetime.fromisoformat(a["published_at"]) >= cutoff]
    selected = (select_world(available, body.top_n, body.sources) if world else
                select_candidates(available, body.focus, body.top_n, body.sources))
    if not selected:
        raise HTTPException(404, "No articles in this window. Try the past 30 days or another source.")
    cache_key = hashlib.sha256(json.dumps([body.model_dump(), [(a["id"], a["title"], a["description"]) for a in selected]], sort_keys=True).encode()).hexdigest()
    if not store and not _generation_lock.acquire(blocking=False):
        raise HTTPException(429, "A digest is being prepared. Please try again in a moment.")
    try:
        cached = _digest_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 600:
            digest = cached[1]
        else:
            if world:
                digest = build_world(selected, body.hours)
            elif store:
                digest = build_digest(selected, body.name.strip() or "Reader", body.focus, store=store)
            else:
                digest = build_digest(selected, body.name.strip() or "Reader", body.focus)
            _digest_cache[cache_key] = (time.monotonic(), digest)
            while len(_digest_cache) > 24:
                _digest_cache.popitem(last=False)
        expires = int(time.time()) + 3600
        preview_id = secrets.token_urlsafe(24) if store else None
        if store:
            store.save_preview(preview_id, digest, expires)
        return {"digest": digest, "expires": expires, "signature": signature(digest, expires), "preview_id": preview_id,
                "source_basis": ("The world edition uses titles and excerpts provided by the linked sources." if world else
                                 "Summaries use publisher RSS titles and excerpts, not full article text.")}
    except (ValueError, RuntimeError):
        raise HTTPException(502, "The AI provider could not complete this digest. Please try again shortly.") from None
    finally:
        if not store:
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
        send_email("Your World Tech Brief", body.digest["markdown"], body.digest["html"], recipients=[os.environ["MY_EMAIL"]])
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
