"""FastAPI entry point detected by Vercel; no database or scraping on import."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import smtplib
import threading
import time
from collections import Counter, OrderedDict, deque
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import ClientDisconnect

load_dotenv()

from app.cache import Cache
from app.mail_schedule import run_due_subscriptions
from app.mail_capacity import batch_sender, mail_capacity
from app.mail_events import router as mail_events_router
from app import public_mail
from app.workspace_delivery import router as workspace_router
from app.sanitation import sanitize_article
from app.news import collect_news
from app.coverage import REGION_LABELS, TOPICS, public_article, region_id, region_matches, topic_for
from app.discovery import (
    COVERAGE_TYPES, InvalidCursor, SortOrder, facet_counts, page_fingerprint, page_result, page_window,
    relevance_score, search_terms, search_text,
)
from app.web_digest import build_digest
from app.world_edition import build_world, select_world
from app.services.email import send_email
from app.ingestion import feed_freshness, refresh_sources, selected_feeds, source_catalog
from app.headlines import HEADLINE_HOURS, build_headlines
from app.launch_store import get_store
from app.public_mail import router as mail_router
from app.selection import select_candidates
from app.sources import BY_ID, GROUPS, KINDS, LANGUAGES

app = FastAPI(title="Informa AI", version="1.1.0", docs_url="/api/docs", redoc_url=None)
app.include_router(mail_router)
app.include_router(mail_events_router)
app.include_router(workspace_router)
PUBLIC = Path(__file__).resolve().parent.parent / "public"
logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 100_000
_limits = OrderedDict()
_limit_lock = threading.Lock()
_generation_lock = threading.Lock()
_digest_cache = Cache("digest-v7")
_news_cache = Cache("news-v9")
_headline_cache = Cache("headlines-v4")
_mail_history = OrderedDict()
NEWS_PAGE_TTL = 60
ARCHIVE_REFRESH_INTERVAL = timedelta(minutes=15)
FEED_FILTERS = ("source", "publisher", "kind", "region", "coverage", "language")


class LimitRequestBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PATCH"}:
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        length = request.headers.get("content-length", "")
        chunks = bytearray()
        if not length.isdecimal() or (len(length) <= 12 and int(length) <= MAX_REQUEST_BYTES):
            try:
                async for chunk in request.stream():
                    if len(chunks) + len(chunk) > MAX_REQUEST_BYTES:
                        break
                    chunks.extend(chunk)
                else:
                    pending = True

                    async def replay():
                        nonlocal pending
                        if pending:
                            pending = False
                            return {"type": "http.request", "body": bytes(chunks)}
                        return await receive()

                    await self.app(scope, replay, send)
                    return
            except ClientDisconnect:
                return
        response = JSONResponse({"detail": "Request is too large."}, status_code=413)
        await response(scope, receive, send)


app.add_middleware(LimitRequestBody)


class TimeWindow(IntEnum):
    half_day = 12
    day = 24
    week = 168
    month = 720


class DigestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edition: Literal["personal", "world"] = "personal"
    name: str = Field(default="Reader", min_length=1, max_length=60)
    focus: str = Field(default="", max_length=400)
    hours: Literal[12, 24, 168, 720] = 168
    top_n: int = Field(default=5, ge=1, le=10)
    sources: list[str] = Field(default_factory=lambda: list(GROUPS), min_length=1, max_length=len(BY_ID))
    pinned_ids: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")]] = Field(
        default_factory=list, max_length=10, validation_alias=AliasChoices("pinned_ids", "pinnedStoryIds"))
    persona: Literal["executive", "engineer", "security", "product"] = "executive"
    topics: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=12)
    topic: str = Field(default="all", max_length=32)
    region: str = Field(default="", max_length=16)
    language: str = Field(default="", max_length=16)

    @field_validator("topic", "region", "language")
    @classmethod
    def known_coverage(cls, value, info):
        choices = {"topic": TOPICS, "region": REGION_LABELS, "language": LANGUAGES}[info.field_name]
        if value not in ("", "all") and value not in choices:
            raise ValueError("Choose a supported topic, publisher region, or language.")
        return ("all" if info.field_name == "topic" else "") if value in ("", "all") else value

    @model_validator(mode="after")
    def fit_pins(self):
        self.pinned_ids = list(dict.fromkeys(self.pinned_ids))
        if len(self.pinned_ids) > self.top_n:
            raise ValueError("Choose a brief length large enough for your pinned stories.")
        return self
    style: Literal["executive", "technical", "skim"] = "executive"

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


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Validation errors must not reflect webhook secret URLs or verification codes.
    details = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
    return JSONResponse({"detail": details}, status_code=422)


def client_key(request: Request):
    address = request.client.host if request.client else "unknown"
    if os.getenv("VERCEL"):
        address = request.headers.get("x-vercel-forwarded-for", address).split(",")[0].strip()
    return hashlib.sha256(address.encode()).hexdigest()


def admit_expensive(store, request: Request, action: str, maximum: int, window: int):
    if not store:
        rate_limit(request, action, maximum, window)
        return
    ip = client_key(request)
    # Browser fingerprint is coarse and cannot replace the stricter IP limit.
    fingerprint = hashlib.sha256(request.headers.get("user-agent", "")[:256].encode()).hexdigest()[:20]
    retry = store.admit_windows([(f"{action}:{ip}", window, maximum),
                                 (f"{action}:{ip}:{fingerprint}", window, maximum)])
    if retry:
        raise HTTPException(429, "Too many requests. Wait a moment and try again.",
                            headers={"Retry-After": str(retry)})


def rate_limit(request: Request, action: str, limit: int, window: int = 600):
    # This bounds requests per warm function instance; it is not a distributed quota.
    key = (client_key(request), action)
    now = time.monotonic()
    with _limit_lock:
        history = _limits.setdefault(key, deque())
        while history and history[0] <= now - window:
            history.popleft()
        if len(history) >= limit:
            retry = max(1, int(history[0] + window - now) + 1)
            raise HTTPException(429, "Please wait a few minutes before trying again.", headers={"Retry-After": str(retry)})
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
    request_id = secrets.token_hex(8)
    started = time.monotonic()
    if request.method in {"POST", "PATCH"}:
        from urllib.parse import urlsplit
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                allowed = parsed.scheme in {"https", "http"} and parsed.netloc == request.headers.get("host")
            except ValueError:
                allowed = False
            if not allowed:
                return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403,
                                    headers={"Cache-Control": "no-store", "X-Request-ID": request_id})
    try:
        response = await call_next(request)
    except SQLAlchemyError as error:
        logger.warning("database_unavailable request_id=%s error_type=%s", request_id, type(error).__name__)
        response = JSONResponse({"detail": "The news database is temporarily unavailable."}, status_code=503)
    except Exception as error:
        logger.error("api_request_failed request_id=%s error_type=%s", request_id, type(error).__name__)
        response = JSONResponse({"detail": "The service could not complete this request. Try again shortly."}, status_code=500)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/") or request.url.path == "/openapi.json":
        response.headers["X-Robots-Tag"] = "noindex"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self' data: https://i.ytimg.com; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    if request.url.path == "/api/docs":
        # Swagger's standard template loads its UI assets from jsDelivr.
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/mail/unsubscribe/"):
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/api"):
        route = request.scope.get("route")
        logger.info("api_request request_id=%s method=%s route=%s status=%d elapsed_ms=%d", request_id,
                    request.method, getattr(route, "path", "unmatched"), response.status_code,
                    (time.monotonic() - started) * 1000)
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "email_configured": public_mail.has_transport()}


@app.get("/api/ready")
def readiness():
    store = get_store()
    if not store:
        return JSONResponse({"status": "unavailable", "reason": "archive_not_configured"}, status_code=503)
    store.ensure_discovery_schema()
    freshness = feed_freshness(source_catalog(store))
    available = freshness["counts"]["fresh"] > 0
    return JSONResponse({"status": freshness["status"], "freshness": freshness}, status_code=200 if available else 503)


@app.get("/api/sources")
def sources():
    return {"sources": source_catalog(get_store()), **discovery_options()}


def discovery_options():
    return {"topics": TOPICS, "regions": REGION_LABELS, "coverage_types": COVERAGE_TYPES, "languages": LANGUAGES}


@app.get("/api/headlines")
def headlines(response: Response):
    store = get_store()
    key = hashlib.sha256(str(store.engine.url if store else "rss").encode()).hexdigest()
    data, _ = _headline_cache.get(key)
    if data is None:
        with _headline_cache.key_lock(key):
            data, _ = _headline_cache.get(key)
            if data is None:
                rows = store.headline_candidates(HEADLINE_HOURS) if store else collect_news()["articles"]
                data = build_headlines(rows)
                if data["articles"]:
                    _headline_cache.put(key, data, ttl=60)
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    if data["articles"]:
        response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=30"
    return data


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


def require_job_secret(authorization):
    secrets_ = [os.getenv(name, "") for name in ("CRON_SECRET", "FEED_REFRESH_SECRET")]
    if not authorization or not any(len(secret) >= 16 and hmac.compare_digest(authorization, f"Bearer {secret}")
                                    for secret in secrets_):
        raise HTTPException(401, "Unauthorized.")


@app.get("/api/jobs/morning")
def morning_job(authorization: str | None = Header(default=None)):
    require_job_secret(authorization)
    if not public_mail.ready():
        return {"status": "disabled"}
    store = source_store()

    def daily_brief():
        if not feed_freshness(source_catalog(store))["counts"]["fresh"]:
            raise HTTPException(503, "Sources are stale. Refresh the archive before processing morning briefs.")
        candidates = store.world_candidates(24, GROUPS)
        selected = select_world(candidates, 5, GROUPS)
        if not selected:
            raise HTTPException(503, "No current stories are available for morning delivery.")
        return build_world(selected, 24, all_pool=candidates)

    return run_due_subscriptions(daily_brief)


@app.get("/api/jobs/mail-health")
def mail_job_health(authorization: str | None = Header(default=None)):
    require_job_secret(authorization)
    capacity = mail_capacity()
    return {"mode": "batch" if batch_sender() and os.getenv("MAIL_PILOT_MODE") != "1" else "single",
            "sending_enabled": public_mail.ready(), "delivery_events_configured": bool(os.getenv("RESEND_WEBHOOK_SECRET")),
            "outbound_daily_limit": capacity.outbound, "digest_daily_limit": capacity.digests,
            **source_store().mail_backlog(time.time())}


@app.get("/api/jobs/refresh")
def refresh_job(authorization: str | None = Header(default=None)):
    require_job_secret(authorization)
    store = source_store()
    lease = store.claim_refresh(scheduled=True)
    if lease is None:
        return {"status": "already_started"}
    cooldown = 0
    try:
        catalog = refresh_sources(store)
        active = [s for s in catalog if s["enabled"]]
        healthy = sum(s["available"] is True for s in active)
        if not healthy:
            raise HTTPException(503, "No enabled feed passed its latest check.")
        cooldown = 240
        return {"status": "refreshed", "sources": len(active), "healthy": healthy}
    finally:
        store.finish_refresh(lease, cooldown=cooldown)


@app.post("/api/admin/refresh")
def refresh_admin(source: str | None = None, authorization: str | None = Header(default=None)):
    require_owner(authorization)
    if source and source not in BY_ID:
        raise HTTPException(404, "Unknown source.")
    store = source_store()
    if not store.admit([("admin-refresh", str(int(time.time()) // 60), 1)]):
        raise HTTPException(429, "Wait a minute before refreshing again.")
    lease = store.claim_refresh()
    if lease is None:
        raise HTTPException(429, "A feed refresh is already running.")
    try:
        return {"sources": refresh_sources(store, source)}
    finally:
        store.finish_refresh(lease)


@app.get("/api/news")
def news(request: Request, response: Response, background: BackgroundTasks,
         hours: TimeWindow = TimeWindow.week, source: str = "all",
         force: bool = False, region: Annotated[str, Query(max_length=16)] = "",
         q: Annotated[str, Query(max_length=150)] = "", kind: str = "all", publisher: str = "", topic: str = "all",
         sort: SortOrder = "latest", coverage: Annotated[str, Query(max_length=24)] = "",
         language: Annotated[str, Query(max_length=16)] = "",
         limit: Annotated[int, Query(ge=1, le=50)] = 24, cursor: Annotated[str | None, Query(max_length=320)] = None):
    if (source not in ("all", *GROUPS) and source not in BY_ID) or kind not in KINDS or (publisher and publisher not in BY_ID):
        raise HTTPException(422, "Choose a supported source or content type.")
    if topic != "all" and topic not in TOPICS:
        raise HTTPException(422, "Choose a supported topic.")
    if (region not in ("", "all", *REGION_LABELS) or coverage not in ("", "all", *COVERAGE_TYPES)
            or language not in ("", "all", *LANGUAGES)):
        raise HTTPException(422, "Choose a supported publisher region, source type, or language.")
    phrase = search_text(q)
    if q.strip() and not search_terms(phrase):
        raise HTTPException(422, "Enter at least one letter or number to search.")
    q = phrase
    region = "" if region == "all" else region
    coverage = "" if coverage == "all" else coverage
    language = "" if language == "all" else language
    store = get_store()
    if force:
        admit_expensive(store, request, "force", 3, 300)
        response.headers["Cache-Control"] = "no-store"
    try:
        if store:
            filters = dict(hours=hours, source=source, query=q, kind=kind, publisher=publisher,
                           limit=limit, cursor=cursor, topic=topic, region=region, sort=sort, coverage=coverage,
                           language=language)
            key = hashlib.sha256(json.dumps([str(store.engine.url), filters], sort_keys=True).encode()).hexdigest()
            # Reuse common views. Arbitrary search terms and cursors stay out of shared Redis.
            cacheable = not q and not cursor
            edge_cacheable = (cacheable and not force and source == "all" and kind == "all" and not publisher
                              and not region and not coverage and not language and sort == "latest" and limit in (12, 24)
                              and not request.headers.get("authorization"))
            cached, stale = _news_cache.get(key) if cacheable and not force else (None, False)
            if cached is not None:
                response.headers["X-Cache"] = "STALE" if stale else "HIT"
                if stale:
                    background.add_task(refresh_cached_page, store, filters, key)
                result = cached
            else:
                response.headers["X-Cache"] = "MISS"
                result = refresh_cached_page(store, filters, key if cacheable else None, force=force)
            result = queue_archive_refresh(background, store, filters, key if cacheable else None, result, force=force)
            if edge_cacheable and result["freshness"]["counts"]["fresh"] and not result.get("refresh_requested"):
                response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
                response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=30, stale-while-revalidate=30"
            return result

        fingerprint = page_fingerprint(hours, source, q, kind, publisher, topic, region, sort, coverage, language)
        ranked = sort == "relevance" and bool(q)
        now, marker = page_window(cursor, fingerprint, ranked=ranked)
        payload = collect_news(force=True) if force else collect_news()
        # A first request can refresh providers before the publication window begins.
        if cursor is None:
            now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        matching = [a for a in payload["articles"] if cutoff <= datetime.fromisoformat(a["published_at"]) <= now
                    and (kind == "all" or a.get("kind") == kind)
                    and (not coverage or (entry := BY_ID.get(a.get("source_id"))) and entry.coverage == coverage)
                    and (not publisher or a.get("source_id") == publisher)]
        if q:
            terms = search_terms(q)
            matching = [dict(a, **({"search_score": score} if ranked else {})) for a in matching
                        if (score := relevance_score(a, q, terms)) is not None]
        matching = [dict(a, topic=topic_for(a)) for a in matching]
        groups = Counter((a.get("source_id"), a["source"], a["topic"]) for a in matching)
        counts = facet_counts(((*key, count) for key, count in groups.items()), source=source, topic=topic, region=region,
                              language=language)
        articles = [a for a in matching if source in ("all", a["source"], a.get("source_id"))
                    and topic in ("all", a["topic"]) and region_matches(a, region)
                    and (not language or BY_ID.get(a.get("source_id")) and BY_ID[a["source_id"]].language == language)]

        def sort_key(article):
            date_key = (article["published_at"], article["id"])
            return (article["search_score"], *date_key) if ranked else date_key

        if marker:
            after = tuple(marker)
            articles = [a for a in articles if sort_key(a) > after] if sort == "oldest" else [a for a in articles if sort_key(a) < after]
        articles.sort(key=sort_key, reverse=sort != "oldest")
        catalog = [dict(feed, region_id=region_id(feed.get("region", "Global"))) for feed in payload.get("sources", [])]
        return {**payload, **discovery_options(), **counts, "sources": catalog,
                **page_result([public_article(a) for a in articles[:limit + 1]], counts["total"], limit, fingerprint, now),
                "freshness": feed_freshness(catalog, source=source, publisher=publisher, kind=kind, region=region,
                                            coverage=coverage, language=language)}
    except InvalidCursor:
        raise HTTPException(400, "This page cursor has expired or changed. Reload stories to start again.") from None


def refresh_cached_page(store, filters, key, *, force=False):
    if key:
        with _news_cache.key_lock(key):
            cached, stale = _news_cache.get(key) if not force else (None, False)
            if cached is not None and not stale:
                return cached
            result = load_archive_page(store, filters)
            _news_cache.put(key, result, ttl=NEWS_PAGE_TTL, stale=NEWS_PAGE_TTL)
            return result
    return load_archive_page(store, filters)


def reader_refresh_scope(catalog, filters, *, force):
    cutoff = (datetime.now(timezone.utc) - ARCHIVE_REFRESH_INTERVAL).isoformat()
    active = [feed for feed in catalog if feed["enabled"]]
    checked = {feed["id"] for feed in active if feed["checked_at"]}
    overdue = {feed["id"] for feed in active if (feed["checked_at"] or "") <= cutoff}
    scoped_filters = {name: filters[name] for name in FEED_FILTERS}
    scoped = selected_feeds(active, **scoped_filters)
    if force and len(scoped) < len(active):
        return {feed["id"] for feed in scoped if feed["id"] in overdue or feed["available"] is False}
    if active and (not checked or len(overdue) == len(active)):
        return None
    scoped_ids = {feed["id"] for feed in scoped}
    pending = scoped_ids - checked if len(checked) * 2 >= len(active) else set()
    scoped_checked = scoped_ids & checked
    if pending or len(scoped_checked & overdue) * 2 > len(scoped_checked):
        return scoped_ids & overdue
    if not force:
        return set()
    return {feed["id"] for feed in scoped if feed["id"] in overdue or feed["available"] is False}


def queue_archive_refresh(background, store, filters, key, page, *, force=False):
    if not filters["cursor"] and reader_refresh_scope(page["sources"], filters, force=force) != set():
        background.add_task(refresh_from_reader, store, filters, key, force=force)
        page = dict(page, refresh_requested=True)
    return page


def refresh_from_reader(store, filters, key, *, force):
    try:
        lease = store.claim_refresh(scheduled=True)
        if lease is None:
            return
        cooldown = 0
        try:
            # Recheck after claiming the lease. Another instance may have updated the archive.
            scope = reader_refresh_scope(source_catalog(store), filters, force=force)
            if scope == set():
                return
            cooldown = 300
            refresh_sources(store, source_ids=scope)
            if key:
                refresh_cached_page(store, filters, key, force=True)
        finally:
            store.finish_refresh(lease, cooldown=cooldown)
    except SQLAlchemyError:
        logger.warning("Could not refresh feeds from the Reading Room")


def load_archive_page(store, filters):
    catalog = source_catalog(store)
    page = store.page(**filters)
    freshness = feed_freshness(catalog, **{name: filters[name] for name in FEED_FILTERS})
    active = [item for item in catalog if item["enabled"]]
    return dict(page, **discovery_options(), articles=[public_article(article) for article in page["articles"]], sources=catalog,
                freshness=freshness,
                fetched_at=max((item["checked_at"] or "" for item in active), default="") or None,
                last_success=max((item["last_success"] or "" for item in active), default="") or None)


@app.post("/api/digest")
def generate(body: DigestRequest, request: Request, response: Response, stream: bool = False):
    world = body.edition == "world"
    if not world and not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "Personalized synthesis is temporarily unavailable. Try the global brief.")
    store = get_store()
    admit_expensive(store, request, "brief", 10, 600)
    if stream:
        return StreamingResponse(digest_stream(body, store), media_type="application/x-ndjson",
                                 headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store, no-transform"})
    result, hit = assemble_digest(body, store)
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
    return result


async def digest_stream(body, store):
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker():
        try:
            result, hit = assemble_digest(body, store, progress=lambda stage: emit({"stage": stage}))
            emit({"result": result, "cached": hit})
        except HTTPException as error:
            emit({"error": error.detail, "status": error.status_code, "retry_after": (error.headers or {}).get("Retry-After")})
        except Exception as error:
            logger.warning("brief_stream_failed error_type=%s", type(error).__name__)
            emit({"error": "The brief could not be prepared. Try again shortly.", "status": 503})
        finally:
            emit(None)

    task = asyncio.create_task(asyncio.to_thread(worker))
    while (event := await queue.get()) is not None:
        yield json.dumps(event) + "\n"
    await task


def assemble_digest(body, store, progress=None):
    world = body.edition == "world"
    name = " ".join(body.name.split()) or "Reader"
    focus = " ".join(", ".join([body.focus, *body.topics]).split()).strip(", ")
    # Include every output-affecting input and a rolling archive boundary.
    inputs = body.model_dump()
    inputs.update(name=name, focus=focus, sources=sorted(body.sources), topics=[])
    archive = str(store.engine.url) if store else "local"
    ttl = 300 if world else 1800
    key = hashlib.sha256(json.dumps([archive, inputs, int(time.time()) // ttl, os.getenv("OPENAI_MODEL")],
                                    sort_keys=True).encode()).hexdigest()
    try:
        digest, _ = _digest_cache.get(key)
        hit = digest is not None
        if not hit:
            lock = _digest_cache.key_lock(key)
            if not lock.acquire(blocking=False):
                raise HTTPException(429, "A brief is already being prepared. Try again shortly.",
                                    headers={"Retry-After": "5"})
            lease = None
            scope = f"brief:{key}"
            try:
                digest, _ = _digest_cache.get(key)
                hit = digest is not None
                if not hit:
                    if store:
                        lease = store.claim_refresh(scope=scope)
                        if lease is None:
                            raise HTTPException(429, "This brief is already being prepared. Try again shortly.",
                                                headers={"Retry-After": "5"})
                        digest, _ = _digest_cache.get(key)
                        hit = digest is not None
                if not hit:
                    digest = prepare_digest(body, store, name, focus, world, progress)
                    _digest_cache.put(key, digest, ttl=60 if digest.get("synthesis", {}).get("degraded") else ttl)
            finally:
                lock.release()
                if lease is not None:
                    store.finish_refresh(lease, scope=scope)
    except (ValueError, RuntimeError):
        raise HTTPException(502, "The AI provider could not complete this digest. Please try again shortly.") from None
    expires = int(time.time()) + 3600
    preview_id = secrets.token_urlsafe(24) if store else None
    if store:
        store.save_preview(preview_id, digest, expires)
    return {"digest": digest, "expires": expires, "signature": signature(digest, expires), "preview_id": preview_id,
            "source_basis": "The brief uses publisher feed titles and excerpts."}, hit


def prepare_digest(body, store, name, focus, world, progress):
    if progress:
        progress(1)
    scope = [label for label in (TOPICS.get(body.topic), REGION_LABELS.get(body.region), LANGUAGES.get(body.language)) if label]
    if not world and not focus:
        focus = ", ".join(scope)
    if store:
        filters = {"topic": body.topic, "region": body.region, "language": body.language}
        available = (store.world_candidates(body.hours, body.sources, **filters) if world else
                     store.candidates(body.hours, body.sources, search_terms(focus), **filters))
        pins = store.pinned_articles(body.pinned_ids)
    else:
        archive = collect_news()["articles"]
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=body.hours)
        available = [article for article in archive if cutoff <= datetime.fromisoformat(article["published_at"]) <= now
                     and (body.topic == "all" or topic_for(article) == body.topic)
                     and region_matches(article, body.region)
                     and (not body.language or BY_ID.get(article.get("source_id"))
                          and BY_ID[article["source_id"]].language == body.language)]
        pins = [article for article in archive if article["id"] in body.pinned_ids]
    pin_map = {article["id"]: article for article in pins}
    if any(ident not in pin_map for ident in body.pinned_ids):
        raise HTTPException(422, "A pinned story is no longer available. Remove it and try again.")
    unpinned = [article for article in available if article["id"] not in pin_map and
                (article["source"] in body.sources or article.get("source_id") in body.sources)]
    pool = [sanitize_article(article) for article in unpinned]
    remaining = body.top_n - len(pins)
    selected = [sanitize_article(pin_map[ident]) for ident in body.pinned_ids]
    if remaining:
        selected.extend(select_world(pool, remaining, body.sources) if world else
                        select_candidates(pool, focus, remaining, body.sources))
    if not selected:
        raise HTTPException(404, "No articles in this window. Try a longer window or another source.")
    if world:
        if progress:
            progress(3)
        return build_world([public_article(article) for article in selected], body.hours, all_pool=pool, scope=scope)
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(429, "A personalized brief is already being prepared. Try again shortly.",
                            headers={"Retry-After": "5"})
    try:
        if store and not store.admit([("generate-total", datetime.now(timezone.utc).date().isoformat(), 60)]):
            raise HTTPException(429, "Personalized synthesis has reached its daily limit. Try the global brief.",
                                headers={"Retry-After": str(86400 - int(time.time()) % 86400)})
        return build_digest(selected, name, focus, store=store, pinned_ids=body.pinned_ids,
                            style=body.style, persona=body.persona, all_pool=pool,
                            progress=progress)
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
        send_email("Your Informa AI", body.digest["markdown"], body.digest["html"], recipients=[os.environ["MY_EMAIL"]])
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
