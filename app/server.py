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

import httpx
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
from app.client_identity import client_address
from app.mail_schedule import run_due_subscriptions
from app.mail_capacity import batch_sender, mail_capacity
from app.mail_events import router as mail_events_router
from app import public_mail, reader_freshness
from app.workspace_delivery import router as workspace_router
from app.sanitation import sanitize_article
from app.brand import BRIEF_SUBJECT, HEADLINE, NAME, PUBLIC_SITE, TAGLINE
from app.coverage import REGION_LABELS, TOPICS, article_source, public_article, region_id, region_matches, topic_for
from app.discovery import (
    COVERAGE_TYPES, InvalidCursor, SortOrder, facet_counts, page_fingerprint, page_result, page_window,
    relevance_score, search_terms, search_text,
)
from app.web_digest import build_digest
from app.world_edition import build_world, select_world
from app.services.email import send_email
from app.ingestion import (PRIORITY_SOURCE_IDS, PRIORITY_WINDOW, SWEEP_CATCHUP, SWEEP_INTERVAL, SWEEP_WINDOW, feed_freshness,
                           latest_priority_check, latest_sweep, refresh_sources, source_catalog, sweep_plan)
from app.headlines import HEADLINE_HOURS, build_headlines
from app.briefing import build_briefing
from app.article_summary import article_summary
from app.curiosity import FORMATS as CURIOSITY_FORMATS, LEVELS as CURIOSITY_LEVELS, MAX_CURIOSITY_CARDS, THEME_LABELS as CURIOSITY_THEMES, build_curiosity_cards, curiosity_article, saved_curiosity_article
from app.search_suggest import suggest as suggest_scopes
from app.query_understanding import understand as understand_query
from app.story_coverage import compare_coverage
from app.trending import extract_trending
from app.launch_store import get_store
from app.public_mail import router as mail_router
from app.selection import select_candidates
from app.sources import BY_ID, GROUPS, KINDS, LANGUAGES
from app.intelligence import SUBJECTS, recommend, related_articles, related_terms, story_identity, subjects_for
from app.reader_signals import ReaderFeedback
from app.syndication import router as syndication_router
from app.discovery_health import router as discovery_router
from app import research as research_service
from app import monitoring
from app import research_projects
from app import ai_insights, event_intelligence
from app.insight_api import router as insight_router

app = FastAPI(title=NAME, description=f"{HEADLINE} {TAGLINE}", version="1.1.0", docs_url=None, redoc_url=None)
app.include_router(mail_router)
app.include_router(mail_events_router)
app.include_router(workspace_router)
app.include_router(syndication_router)
app.include_router(discovery_router)
app.include_router(monitoring.router)
app.include_router(insight_router)
app.include_router(research_projects.router)
app.include_router(research_projects.public_router)
PUBLIC = Path(__file__).resolve().parent.parent / "public"
logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 100_000
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_limits = OrderedDict()
_limit_lock = threading.Lock()
_generation_lock = threading.Lock()
_digest_cache = Cache("digest-v11")
_news_cache = Cache("news-v17")
_headline_cache = Cache("headlines-v8")
_signals_cache = Cache("signals-v1")
_trending_cache = Cache("trending-v7")
_briefing_cache = Cache("briefing-v2")
_curiosity_cache = Cache("curiosity-v2")
_suggest_cache = Cache("suggest-authors-v1")
_mail_history = OrderedDict()
NEWS_PAGE_TTL = 60
FEED_FILTERS = ("source", "publisher", "kind", "region", "coverage", "language")


class LimitRequestBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in WRITE_METHODS:
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        lengths = request.headers.getlist("content-length")
        if len(lengths) > 1 or lengths and (not lengths[0].isascii() or not lengths[0].isdecimal()):
            await JSONResponse({"detail": "Invalid request length."}, status_code=400)(scope, receive, send)
            return
        length = lengths[0] if lengths else ""
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
    archive = 2160


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
    coverage: str = Field(default="", max_length=24)
    subject: str = Field(default="", max_length=24)

    @field_validator("topic", "region", "language", "coverage", "subject")
    @classmethod
    def known_coverage(cls, value, info):
        choices = {"topic": TOPICS, "region": REGION_LABELS, "language": LANGUAGES,
                   "coverage": COVERAGE_TYPES, "subject": SUBJECTS}[info.field_name]
        if value not in ("", "all") and value not in choices:
            raise ValueError("Choose a supported topic, publisher region, language, or source type.")
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


class SourceRefresh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[str] = Field(min_length=1, max_length=12)

    @field_validator("source_ids")
    @classmethod
    def reviewed_sources(cls, values):
        if any(value not in BY_ID for value in values):
            raise ValueError("Choose reviewed source IDs.")
        return list(dict.fromkeys(values))


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
    # IPv6 clients are keyed by /64 so address rotation cannot multiply a quota.
    return hashlib.sha256(client_address(request).encode()).hexdigest()


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


MIN_OWNER_TOKEN = 32
PRIVILEGED_PREFIXES = ("/api/admin", "/api/email", "/api/jobs/")
AUTH_FAILURE_LIMIT = 10
AUTH_FAILURE_WINDOW = 900
_auth_failures = OrderedDict()
# Per-client budgets for public reads that reach the database and bypass the CDN cache.
READ_LIMITS = (
    ("/api/articles/", "read-article", 120),
    ("/api/authors", "read-authors", 30),
    ("/api/briefing", "read-briefing", 120),
    ("/api/discovery/coverage", "read-coverage", 30),
    ("/api/discovery/sources/", "read-source-health", 60),
    ("/api/intelligence/events", "read-developments", 60),
    ("/api/intelligence/technologies/", "read-technology", 60),
    ("/api/news", "read-news", 120),
    ("/api/search/suggest", "read-suggest", 240),
)


def owner_secret() -> str:
    """Return ADMIN_TOKEN only when it is long enough to resist guessing."""
    secret = os.getenv("ADMIN_TOKEN", "")
    if secret and len(secret) < MIN_OWNER_TOKEN:
        logger.warning("owner_token_too_short minimum=%d", MIN_OWNER_TOKEN)
        return ""
    return secret


def signature(digest: dict, expires: int) -> str:
    secret = owner_secret()
    if not secret:
        return ""
    # Previews are signed with a derived key. The owner bearer token is never used as a public MAC key.
    key = hmac.new(secret.encode(), b"informa:preview-signature:v1", hashlib.sha256).digest()
    message = json.dumps({"digest": digest, "expires": expires}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def require_owner(authorization: str | None, *, detail="Enter the owner access key to send to the configured Gmail inbox."):
    secret = owner_secret()
    if not secret or not authorization or not hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
        raise HTTPException(401, detail)


def read_budget(request: Request):
    path = request.url.path
    for prefix, action, limit in READ_LIMITS:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            try:
                rate_limit(request, action, limit, 60)
            except HTTPException as error:
                return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)
            return None
    return None


def privileged_path(path: str) -> bool:
    return path.startswith(PRIVILEGED_PREFIXES)


def auth_failures(request: Request, *, record=False):
    """Count failed owner or scheduler authorizations per client within this instance."""
    key = client_key(request)
    now = time.monotonic()
    with _limit_lock:
        history = _auth_failures.setdefault(key, deque())
        while history and history[0] <= now - AUTH_FAILURE_WINDOW:
            history.popleft()
        if record:
            history.append(now)
        _auth_failures.move_to_end(key)
        while len(_auth_failures) > 2000:
            _auth_failures.popitem(last=False)
        retry = int(history[0] + AUTH_FAILURE_WINDOW - now) + 1 if history else 0
        return len(history), max(1, retry)


def allowed_write_origin(request: Request):
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True  # Service callers use bearer tokens or provider signatures.
    scheme = "https" if os.getenv("VERCEL") else request.url.scheme
    return origin == f"{scheme}://{request.url.netloc}"


@app.middleware("http")
async def response_headers(request: Request, call_next):
    request_id = secrets.token_hex(8)
    started = time.monotonic()
    privileged = privileged_path(request.url.path)
    try:
        failures, retry = auth_failures(request) if privileged else (0, 0)
        if failures >= AUTH_FAILURE_LIMIT:
            response = JSONResponse({"detail": "Too many failed authorization attempts. Try again later."},
                                    status_code=429, headers={"Retry-After": str(retry)})
        elif request.method in WRITE_METHODS and not allowed_write_origin(request):
            response = JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        elif request.method == "GET" and (limited := read_budget(request)) is not None:
            response = limited
        else:
            response = await call_next(request)
            if privileged and response.status_code == 401:
                auth_failures(request, record=True)
                logger.warning("privileged_auth_failed request_id=%s path=%s", request_id, request.url.path)
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
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.scheme == "https" or os.getenv("VERCEL"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self' data: https://i.ytimg.com https://media.dev.to https://media2.dev.to https://cdn.hashnode.com https://images.unsplash.com https://techcrunch.com https://theverge.com https://arstechnica.com https://cdn.arstechnica.net https://media.wired.com https://cdn.vox-cdn.com https://platform.theverge.com; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    if request.url.path == "/api/docs":
        # Swagger's standard template loads its UI assets from jsDelivr.
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/mail/unsubscribe/"):
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    response.headers["Content-Security-Policy"] += "; object-src 'none'"
    if request.url.path.startswith("/api") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/api"):
        route = request.scope.get("route")
        logger.info("api_request request_id=%s method=%s route=%s status=%d elapsed_ms=%d", request_id,
                    request.method, getattr(route, "path", "unmatched"), response.status_code,
                    (time.monotonic() - started) * 1000)
    return response


def api_docs_enabled() -> bool:
    """Swagger UI loads third-party scripts with inline code, so production serves it only on request."""
    configured = os.getenv("API_DOCS_ENABLED")
    if configured is not None:
        return configured == "1"
    return os.getenv("VERCEL_ENV") != "production"


@app.get("/api/docs", include_in_schema=False)
def api_docs():
    if not api_docs_enabled():
        raise HTTPException(404, "Not Found")
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(openapi_url=app.openapi_url, title=f"{NAME} API")


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
    freshness = feed_freshness(source_catalog(store, include_archive=False))
    available = freshness["counts"]["fresh"] > 0
    return JSONResponse({"status": freshness["status"], "freshness": freshness}, status_code=200 if available else 503)


@app.get("/api/sources")
def sources():
    return {"sources": source_catalog(get_store()), **discovery_options()}


def collect_news():
    # An unconfigured archive must never turn public reads into a live publisher sweep.
    return {"articles": [], "sources": source_catalog(), "fetched_at": None}


def discovery_options():
    return {"topics": TOPICS, "subjects": SUBJECTS, "regions": REGION_LABELS,
            "coverage_types": COVERAGE_TYPES, "languages": LANGUAGES}


@app.get("/api/curiosity")
def curiosity(limit: int = Query(default=24, ge=1, le=MAX_CURIOSITY_CARDS)):
    """Return reviewed evergreen engineering insights plus quality-ranked archive cards.

    This endpoint reads the local archive only and never fetches a publisher; feeds are collected
    by the scheduled sweeps. Results are cached for 30 minutes per ``limit``.
    """
    key = str(limit)
    cards, _ = _curiosity_cache.get(key)
    if cards is None:
        with _curiosity_cache.key_lock(key):
            cards, _ = _curiosity_cache.get(key)
            if cards is None:
                cards = build_curiosity_cards(get_store(), limit=limit)
                _curiosity_cache.put(key, cards, ttl=1800)
    return {"cards": cards, "updated_at": datetime.now(timezone.utc).isoformat(), "selection_limit": 5,
            "themes": [{"id": ident, "label": label} for ident, label in CURIOSITY_THEMES.items()],
            "formats": [{"id": ident, "label": label} for ident, label in CURIOSITY_FORMATS.items()],
            "levels": [{"id": ident, "label": label} for ident, label in CURIOSITY_LEVELS.items()]}


class RecommendationScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: TimeWindow = TimeWindow.week
    source: str = Field(default="all", max_length=64)
    publisher: str = Field(default="", max_length=64)
    kind: str = Field(default="all", max_length=24)
    topic: str = Field(default="all", max_length=24)
    region: str = Field(default="", max_length=16)
    coverage: str = Field(default="", max_length=24)
    language: str = Field(default="", max_length=16)
    subject: str = Field(default="", max_length=24)

    @model_validator(mode="after")
    def supported_scope(self):
        if (self.source not in ("all", *GROUPS, *BY_ID) or (self.publisher and self.publisher not in BY_ID)
                or self.kind not in KINDS or self.topic not in ("all", *TOPICS)
                or self.region not in ("", *REGION_LABELS) or self.coverage not in ("", *COVERAGE_TYPES)
                or self.language not in ("", *LANGUAGES) or self.subject not in ("", *SUBJECTS)):
            raise ValueError("Choose supported filters for your recommendations.")
        return self


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[str] = Field(default_factory=list, max_length=10)
    subjects: list[str] = Field(default_factory=list, max_length=12)
    sources: list[str] = Field(default_factory=list, max_length=50)
    authors: list[Annotated[str, Field(pattern=r"^author-[a-f0-9]{32}$")]] = Field(default_factory=list, max_length=30)
    exclude_ids: list[str] = Field(default_factory=list, max_length=100)
    saved_ids: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")]] = Field(default_factory=list, max_length=8)
    q: str = Field(default="", max_length=150)
    limit: int = Field(default=24, ge=1, le=50)
    scope: RecommendationScope = Field(default_factory=RecommendationScope)
    feedback: ReaderFeedback = Field(default_factory=ReaderFeedback)

    @model_validator(mode="after")
    def supported_preferences(self):
        if (any(topic not in TOPICS for topic in self.topics) or any(key not in SUBJECTS for key in self.subjects)
                or any(source not in (*GROUPS, *BY_ID) for source in self.sources)
                or any(not 1 <= len(ident) <= 40 for ident in self.exclude_ids)):
            raise ValueError("Choose supported interests and sources.")
        if self.q.strip() and not search_terms(self.q):
            raise ValueError("Enter at least one letter or number to search.")
        return self


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=320)
    article_id: str = Field(default="", max_length=40, pattern=r"^[a-zA-Z0-9_-]*$")
    mode: Literal["search", "analyze", "compare", "brief", "global_compare"] = "search"
    language: Literal[tuple(research_service.OUTPUT_LANGUAGES)] = "en"
    scope: RecommendationScope = Field(default_factory=RecommendationScope)

    @model_validator(mode="after")
    def valid_question(self):
        if (not self.article_id and not search_terms(self.q)) or (
            self.article_id and (self.q or self.mode not in {"analyze", "compare"})
        ):
            raise ValueError("Enter a question or analyze an archived article.")
        return self


class WatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    watches: list[monitoring.Watch] = Field(min_length=1, max_length=6)


@app.post("/api/intelligence/research")
def archive_research(body: ResearchRequest, request: Request):
    store = source_store()
    admit_expensive(store, request, "archive-research", 12, 60)
    scope = body.scope.model_dump()
    anchor = None
    question = body.q
    if body.article_id:
        pinned = store.pinned_articles([body.article_id])
        if not pinned:
            raise HTTPException(404, "This story is no longer in the available archive.")
        anchor = pinned[0]
        question = anchor["title"][:320]
        # Article analysis uses current related coverage even for an older archive link.
        scope = RecommendationScope(hours=TimeWindow.month).model_dump()
    result = research_service.research(store, question=question, mode=body.mode, filters=scope, anchor=anchor, language=body.language)
    source_ids = {row.get("source_id") for row in result["evidence"]}
    return {**result, "coverage_freshness": reader_freshness.coverage_snapshot(store, topics=[scope["topic"]],
             source_ids=source_ids, filters={key: scope[key] for key in ("source", "publisher", "kind", "region", "coverage", "language")})}


@app.get("/api/intelligence/daily")
def research_daily():
    store = get_store()
    saved = research_service.recent_research_brief(store) if store else None
    source_edition = None
    if store and not saved:
        current = cached_briefing(store, 24)
        evidence = [research_service.evidence_record(row) for row in current["articles"]]
        if evidence:
            source_edition = {"evidence": evidence, "updated_at": current["updated_at"], "basis": "publisher_evidence"}
    return {"status": "available" if saved else "pending",
            "brief": saved, "source_edition": source_edition, "ai_available": research_service.ai_enabled()}


@app.get("/api/intelligence/options")
def research_options():
    return {"topics": TOPICS, "analysis_enabled": research_service.ai_enabled(),
            "semantic_configured": research_service.vectors_enabled()}


@app.post("/api/intelligence/watch")
def research_watch(body: WatchRequest, request: Request):
    store = source_store()
    admit_expensive(store, request, "archive-watch", 8, 60)
    return {"watches": research_service.watch_matches(store, body.watches),
            "checked_at": datetime.now(timezone.utc).isoformat()}


def intelligence_candidates(store, hours=168, *, scope=None, query="", interests=None):
    filters = scope.model_dump(exclude={"hours"}) if scope else {}
    if store:
        return store.world_candidates(hours, (), query=query, interests=interests, **filters)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    result = []
    for article in collect_news()["articles"]:
        try:
            if cutoff <= datetime.fromisoformat(article["published_at"]) <= now:
                if not scope or recommendation_scope_matches(article, scope):
                    result.append(article)
        except (KeyError, TypeError, ValueError):
            continue
    return result


def recommendation_scope_matches(article, scope):
    entry = article_source(article)
    return (scope.source in ("all", article["source"], article.get("source_id"))
            and (not scope.publisher or scope.publisher == article.get("source_id"))
            and scope.kind in ("all", article.get("kind")) and scope.topic in ("all", topic_for(article))
            and region_matches(article, scope.region)
            and (not scope.coverage or entry and scope.coverage == entry.coverage)
            and (not scope.language or entry and scope.language == entry.language)
            and (not scope.subject or scope.subject in subjects_for(article)))


@app.post("/api/recommendations")
def recommendations(body: RecommendationRequest, request: Request, response: Response):
    store = get_store()
    rate_limit(request, "recommendations", 60)
    response.headers["Cache-Control"] = "no-store"
    query = search_text(body.q)
    related_subjects = []
    liked_subjects = []
    if store and body.saved_ids:
        counts = Counter(subject for row in store.pinned_articles(body.saved_ids) for subject in subjects_for(row))
        related_subjects = [subject for subject, _ in counts.most_common(6)]
    if store and body.feedback.liked_ids:
        counts = Counter(subject for row in store.pinned_articles(body.feedback.liked_ids) for subject in subjects_for(row))
        liked_subjects = [subject for subject, _ in counts.most_common(6)]
    sampling = body.model_copy(update={"subjects": list(dict.fromkeys([*body.subjects, *related_subjects, *liked_subjects])),
                                       "exclude_ids": [*body.exclude_ids, *body.saved_ids, *body.feedback.liked_ids]})
    candidates = intelligence_candidates(store, body.scope.hours, scope=body.scope, query=query, interests=sampling)
    ranked = recommend(candidates, topics=body.topics, subjects=body.subjects, preferred_sources=body.sources,
                       authors=body.authors, exclude_ids=sampling.exclude_ids, query=query, limit=body.limit,
                       hours=body.scope.hours, related_subjects=related_subjects, liked_subjects=liked_subjects,
                       muted_topics=body.feedback.muted_topics, companies=body.feedback.companies)
    if store and ranked["articles"]:
        enriched = store.with_reading_access(ranked["articles"])
        for article in enriched:
            if access := article.pop("_reading_access", None):
                article.update(reading_access=access, reading_policy="full_text")
        ranked["articles"] = enriched
    return {**ranked, "scope": body.scope.model_dump()}


@app.get("/api/authors")
def author_catalog(response: Response, q: Annotated[str, Query(max_length=80)] = "",
                   limit: Annotated[int, Query(ge=1, le=100)] = 80):
    phrase = search_text(q)
    authors = {}
    for row in intelligence_candidates(get_store()):
        article = public_article(row)
        key = article["author_key"]
        if not key or phrase and phrase not in search_text(article.get("author", "")):
            continue
        if key not in authors:
            authors[key] = {"id": key, "name": article["author"], "source": article["source"],
                "publisher": article["publisher"], "profile_url": article.get("author_url"), "articles": 0}
        authors[key]["articles"] += 1
    response.headers["Cache-Control"] = "public, max-age=60"
    return {"authors": sorted(authors.values(), key=lambda row: (-row["articles"], row["name"].casefold()))[:limit],
            "basis": "Authors observed in the recent discovery sample. RSS names are scoped to their source feed."}


def recent_authors():
    """Author names from the bounded recent sample, cached briefly for type-ahead use."""
    cached, _ = _suggest_cache.get("authors")
    if cached is not None:
        return cached["authors"]
    authors = {}
    try:
        for row in intelligence_candidates(get_store()):
            article = public_article(row)
            key = article.get("author_key")
            if key and key not in authors and article.get("author"):
                authors[key] = {"id": key, "name": article["author"], "publisher": article.get("publisher", "")}
    except SQLAlchemyError:
        logger.warning("search_suggest_authors_unavailable")
        return []
    rows = list(authors.values())
    _suggest_cache.put("authors", {"authors": rows}, ttl=300)
    return rows


@app.get("/api/search/suggest")
def search_suggest(response: Response, q: Annotated[str, Query(max_length=80)] = ""):
    """Scope suggestions for the search box: topics, subjects, publisher feeds and authors."""
    phrase = q.strip()
    suggestions = suggest_scopes(phrase, topics=TOPICS, subjects=SUBJECTS, sources=BY_ID.values(),
                                 authors=recent_authors() if len(phrase) >= 2 else ())
    interpretation = understand_query(phrase, topics=TOPICS, regions=REGION_LABELS, coverage_types=COVERAGE_TYPES,
                                      subjects=SUBJECTS, sources=BY_ID.values())
    response.headers["Cache-Control"] = "public, max-age=60"
    return {"query": phrase, "suggestions": suggestions, "interpretation": interpretation}


@app.get("/api/articles/{article_id}")
def article_details(article_id: str, response: Response):
    if not 1 <= len(article_id) <= 40 or not all(c.isalnum() or c in "-_" for c in article_id):
        raise HTTPException(422, "Invalid article ID.")
    store = get_store()
    rows = None if store else collect_news()["articles"]
    raw = store.article(article_id) if store else next((row for row in rows if row["id"] == article_id), None)
    if not raw:
        raise HTTPException(404, "This story is no longer in the archive. Open its original source if you saved the link.")
    article = public_article(raw)
    candidates = store.related_candidates(article_id, related_terms(article)) if store else rows
    now = datetime.now(timezone.utc).isoformat()
    eligible = [row for row in candidates if row["published_at"] <= now]
    coverage = compare_coverage(article, eligible)
    related = related_articles(article, candidates)
    if store:
        related = [*related, *semantic_related(store, raw, exclude={article_id, *(row["id"] for row in related),
                                                                    *(row["id"] for row in coverage)}, limit=max(0, 8 - len(related)))]
        related = store.with_reading_access(related)
        coverage = store.with_reading_access(coverage)
    reading = raw.get("_reading_content")
    seen_in = store.article_feed_ids(article_id) if store else raw.get("_feed_ids", ())
    indexed_by = [dict(id=entry.id, label=entry.label) for entry in BY_ID.values()
                  if entry.id in seen_in and entry.id != article.get("source_id")]
    response.headers["Cache-Control"] = "no-store"
    return {"article": article, "related": [public_article(item) for item in related],
            "development_id": event_intelligence.development_for_article(store, article_id) if store else None,
            "coverage": [public_article(item) for item in coverage],
            "reading": reading,
            "reading_notice": ("Full text shared with permission from the rights holder. Original source and attribution are preserved."
                if reading else "Publisher-supplied excerpt. Read the original for the complete article, images and any subscriber content."
                if article["has_excerpt"] else "Headline and source link only. The article body has not been retrieved or summarized."),
            "summary": article_summary(article, reading), "also_indexed_by": indexed_by}


def semantic_related(store, raw, *, exclude, limit=4):
    """Stories close in meaning to an article, using its stored embedding. No model call is made."""
    if limit <= 0 or not research_service.vectors_enabled():
        return []
    try:
        rows, status = research_service.vector_results(store, raw["title"], 720, {}, anchor=raw)
    except SQLAlchemyError as error:
        logger.warning("semantic_related_unavailable error_type=%s", type(error).__name__)
        return []
    if status != "ready":
        return []
    seen = {story_identity(raw)}
    selected = []
    for row in rows:
        identity = story_identity(row)
        if row["id"] in exclude or identity in seen:
            continue
        seen.add(identity)
        selected.append(dict(row, related_reason="Similar in meaning"))
        if len(selected) >= limit:
            break
    return selected


@app.get("/api/headlines")
def headlines(response: Response):
    store = get_store()
    key = hashlib.sha256(str(store.engine.url if store else "rss").encode()).hexdigest()
    data, _ = _headline_cache.get(key)
    if data is None:
        with _headline_cache.key_lock(key):
            data, _ = _headline_cache.get(key)
            if data is None:
                rows = store.headline_candidates(HEADLINE_HOURS, include_primary=True) if store else collect_news()["articles"]
                data = build_headlines(rows)
                if data["articles"]:
                    _headline_cache.put(key, data, ttl=60)
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    if data["articles"]:
        response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=30"
    return data


@app.get("/api/signals")
def signals(response: Response):
    from app.signals import priority_signals
    store = get_store()
    key = hashlib.sha256(str(store.engine.url if store else "rss").encode()).hexdigest()
    data, _ = _signals_cache.get(key)
    if data is None:
        with _signals_cache.key_lock(key):
            data, _ = _signals_cache.get(key)
            if data is None:
                rows = store.headline_candidates(24, include_primary=True, per_source=40) if store else collect_news()["articles"]
                data = priority_signals(rows)
                _signals_cache.put(key, data, ttl=60)
    response.headers["Cache-Control"] = "public, max-age=30"
    return data


@app.get("/api/trending")
def trending(response: Response):
    store = get_store()
    key = hashlib.sha256(str(store.engine.url if store else "rss").encode()).hexdigest()
    data, _ = _trending_cache.get(key)
    if data is None:
        with _trending_cache.key_lock(key):
            data, _ = _trending_cache.get(key)
            if data is None:
                rows = intelligence_candidates(store, 48)
                data = extract_trending(rows)
                if data["trending"]:
                    _trending_cache.put(key, data, ttl=120)
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    if data and data.get("trending"):
        response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=60"
    return data


def cached_briefing(store, hours):
    key = hashlib.sha256(json.dumps([str(store.engine.url) if store else "rss", hours]).encode()).hexdigest()
    data, _ = _briefing_cache.get(key)
    if data is None:
        with _briefing_cache.key_lock(key):
            data, _ = _briefing_cache.get(key)
            if data is None:
                data = build_briefing(intelligence_candidates(store, hours), hours=hours)
                if data["articles"]:
                    _briefing_cache.put(key, data, ttl=60)
    return data


@app.get("/api/briefing")
def daily_briefing(response: Response, hours: Annotated[int, Query(ge=12, le=168)] = 24):
    store = get_store()
    data = cached_briefing(store, hours)
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    if data["articles"]:
        response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=30"
    return {**data, "freshness": feed_freshness(source_catalog(store, include_archive=False))}


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
    search_index = store.migrate()
    return {"database": store.engine.dialect.name, "schema_ready": True, "search_index": search_index}


@app.get("/api/admin/ai-usage")
def ai_usage_report(authorization: str | None = Header(default=None)):
    """Owner view of AI routing, recorded usage and estimated spend for the retained seven days."""
    require_owner(authorization, detail="Enter a valid owner access key to view AI usage.")
    from app import ai_usage
    from app.agent import openai_client
    store = source_store()
    rows = ai_usage.summary(store)
    days = {}
    for row in rows:
        total = days.setdefault(row["day"], {"day": row["day"], "calls": 0, "failures": 0, "prompt": 0,
                                             "completion": 0, "estimated_usd": 0.0})
        for key in ("calls", "failures", "prompt", "completion"):
            total[key] += row[key]
        total["estimated_usd"] = round(total["estimated_usd"] + (row["estimated_usd"] or 0), 6)
    tiers = sorted(set(openai_client.TASK_TIERS.values()))
    return {"routing": {tier: openai_client.route_model(next(task for task, value in openai_client.TASK_TIERS.items()
                                                             if value == tier)) for tier in tiers},
            "fallback_model": openai_client.fallback_model(""), "tasks": openai_client.TASK_TIERS,
            "daily_budget_usd": ai_usage.daily_budget() or None, "spend_today_usd": ai_usage.spend_today(store),
            "days": sorted(days.values(), key=lambda row: row["day"], reverse=True), "breakdown": rows,
            "basis": "Estimated from recorded token counts and list prices. Check the provider dashboard for billing."}


@app.patch("/api/admin/sources/{source_id}")
def update_source(source_id: str, body: SourceUpdate, authorization: str | None = Header(default=None)):
    require_owner(authorization)
    if source_id not in BY_ID:
        raise HTTPException(404, "Unknown source.")
    source = BY_ID[source_id]
    if body.enabled and not source.enabled:
        raise HTTPException(409, source.pause_reason or "This integration is paused in the source catalog.")
    source_store().enable(source_id, body.enabled)
    return {"source": source_id, "enabled": body.enabled}


def require_job_secret(authorization):
    secrets_ = [os.getenv(name, "") for name in ("CRON_SECRET", "FEED_REFRESH_SECRET")]
    if not authorization or not any(len(secret) >= 16 and hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode())
                                    for secret in secrets_):
        raise HTTPException(401, "Unauthorized.")


@app.get("/api/jobs/intelligence")
def research_job(authorization: str | None = Header(default=None)):
    require_job_secret(authorization)
    return run_intelligence_check(source_store())


def run_intelligence_check(store):
    lease_scope = "research-index-lease"
    lease = store.claim_refresh(scheduled=True, scope=lease_scope)
    if lease is None:
        return {"status": "already_started"}
    try:
        research_service.take_provider_issue()
        watch_progress = run_monitoring_check(store, scheduled=True)
        progress = research_service.index_archive(store)
        event_progress = event_intelligence.sync(store)
        brief = research_service.refresh_research_brief(store)
        try:
            ai_insights.prepare_recent_changes(store)
        except SQLAlchemyError as error:
            logger.warning("change_preparation_failed error_type=%s", type(error).__name__)
        result = {"status": "checked", **watch_progress, **progress, **event_progress, "brief_status": brief}
        if issue := research_service.take_provider_issue():
            # A coarse category only; provider messages can echo request details.
            result["ai_issue"] = issue
            result["ai_action_required"] = issue in research_service.CONFIGURATION_ISSUES
            log = logger.error if result["ai_action_required"] else logger.warning
            log("intelligence_ai_issue issue=%s index_status=%s brief_status=%s", issue,
                progress.get("index_status"), brief)
        return result
    finally:
        store.finish_refresh(lease, cooldown=240, scope=lease_scope)


def run_monitoring_check(store, *, scheduled=False):
    scope = "research-monitor-lease"
    lease = store.claim_refresh(scheduled=scheduled, scope=scope)
    if lease is None:
        return {"monitoring_status": "already_started", "watches_checked": 0, "alerts_created": 0}
    try:
        return monitoring.run_monitoring(store)
    except SQLAlchemyError as error:
        logger.warning("research_monitor_error type=%s", type(error).__name__)
        return {"monitoring_status": "unavailable", "watches_checked": 0, "alerts_created": 0}
    finally:
        store.finish_refresh(lease, cooldown=240 if scheduled else 0, scope=scope)


@app.post("/api/admin/monitoring/check")
def check_monitoring(authorization: str | None = Header(default=None)):
    require_owner(authorization, detail="Enter a valid owner access key to check monitoring.")
    return run_monitoring_check(source_store())


@app.get("/api/jobs/morning")
def morning_job(authorization: str | None = Header(default=None)):
    require_job_secret(authorization)
    if not public_mail.ready():
        return {"status": "disabled"}
    store = source_store()

    def daily_brief():
        if not feed_freshness(source_catalog(store, include_archive=False))["counts"]["fresh"]:
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


# A sweep that outgrows one function run hands the rest to a fresh run straight away instead
# of waiting for GitHub's follow-up, which can start hours late. Each run checks feeds that
# are still unchecked in the same sweep, so a publisher is never fetched twice per sweep.
SWEEP_CHAIN_LIMIT = 6
SWEEP_RUN_SECONDS = 230


def continue_sweep(result, hop):
    """Start the next run of an unfinished sweep; returns True when one was handed off."""
    if (os.getenv("VERCEL_ENV") != "production" or hop >= SWEEP_CHAIN_LIMIT
            or result.get("status") != "refreshed" or not result.get("remaining")):
        return False
    secret = os.getenv("CRON_SECRET", "")
    if len(secret) < 16:
        return False
    try:
        httpx.get(f"{PUBLIC_SITE}/api/jobs/refresh", params={"run": "continue", "hop": hop + 1},
                  headers={"Authorization": f"Bearer {secret}", "User-Agent": "InformaAI-sweep/1.0"},
                  timeout=httpx.Timeout(4, connect=4),
                  follow_redirects=False)
    except httpx.TimeoutException:
        pass  # Expected: the next run keeps working after this one stops waiting for its reply.
    except httpx.HTTPError as error:
        logger.warning("publisher_sweep_handoff_failed hop=%s error_type=%s", hop + 1, type(error).__name__)
        return False
    logger.info("publisher_sweep_handoff hop=%s remaining=%s", hop + 1, result.get("remaining"))
    return True


@app.get("/api/jobs/refresh")
def refresh_job(run: str | None = None, hop: Annotated[int, Query(ge=0, le=SWEEP_CHAIN_LIMIT)] = 0,
                authorization: str | None = Header(default=None)):
    require_job_secret(authorization)
    if run == "priority":
        return run_sweep(priority=True)
    if run == "continue":
        result = run_sweep(continuation=True)
        result["handed_off"] = continue_sweep(result, hop)
        return result
    if run != "scheduled":
        return {"status": "inactive"}  # Legacy workers and fallback crons cannot fetch.
    return run_sweep()


@app.post("/api/jobs/feed-sweep")
def scheduled_feed_sweep(response: Response, authorization: str | None = Header(default=None),
                         scheduled_at: str = Header(alias="ce-vssscheduledat", max_length=48)):
    secret = os.getenv("CRON_SECRET", "")
    if len(secret) < 16 or not hmac.compare_digest(authorization or "", f"Bearer {secret}"):
        raise HTTPException(401, "Unauthorized.")
    if os.getenv("VERCEL_ENV") in {"preview", "development"}:
        return {"status": "inactive"}
    try:
        scheduled = datetime.fromisoformat(scheduled_at)
    except ValueError as exc:
        raise HTTPException(422, "Invalid sweep time.") from exc
    result = run_sweep(expected_slot=scheduled)
    result["handed_off"] = continue_sweep(result, 0)
    incomplete = result["status"] == "closed" or result.get("remaining") or result.get("unconfirmed")
    if incomplete:
        response.status_code = 503
        for ident in result.get("unconfirmed", ()):
            logger.error("publisher_check_interrupted source_id=%s scheduled=%s", ident, scheduled.isoformat())
        for ident in result.get("unfinished", ()):
            logger.log(logging.INFO if result["handed_off"] else logging.ERROR,
                       "publisher_check_not_started source_id=%s scheduled=%s reason=sweep_budget handed_off=%s",
                       ident, scheduled.isoformat(), result["handed_off"])
    logger.log(logging.WARNING if incomplete or result.get("deferrals") else logging.INFO,
               "publisher_sweep scheduled=%s status=%s checked=%s healthy=%s remaining=%s deferred=%s unconfirmed=%s",
               scheduled.isoformat(), result["status"], result.get("checked"), result.get("healthy"),
               result.get("remaining"), result.get("deferrals"), result.get("unconfirmed"))
    return result


def run_sweep(*, source=None, source_ids=None, owner=False, expected_slot=None, priority=False, continuation=False):
    """Check publishers once per slot: every source at 08:00/20:00 IST, the busiest also at 02:00/14:00 IST."""
    now = datetime.now(timezone.utc)
    scheduled = latest_priority_check(now) if priority else latest_sweep(now)
    # Vercel's scheduled delivery must arrive inside the sweep window; the follow-up and owner
    # recovery may finish the same sweep later, before the next one starts.
    window = PRIORITY_WINDOW if priority else SWEEP_WINDOW if expected_slot is not None else SWEEP_CATCHUP
    if priority:
        source_ids = PRIORITY_SOURCE_IDS
    closes = scheduled + window
    next_sweep = (scheduled + SWEEP_INTERVAL).isoformat()
    if now >= closes or (expected_slot is not None and expected_slot != scheduled):
        return {"status": "closed", "scheduled_at": next_sweep}

    store = source_store()
    if owner and not store.admit([("admin-refresh", str(int(time.time()) // 60), 4 if source_ids and not source else 1)]):
        raise HTTPException(429, "Wait a minute before refreshing again.")
    lease = store.claim_refresh(lease_seconds=360)
    if lease is None:
        if owner:
            raise HTTPException(429, "A feed refresh is already running.")
        return {"status": "already_started"}
    try:
        slot = scheduled.isoformat(timespec="minutes")
        before = store.source_state(include_archive=False)
        attempts = store.feed_attempts(slot)
        pending, deferred = sweep_plan(before, scheduled, now, attempts=attempts, source_ids=source_ids,
                                       host_backoffs=store.feed_host_backoffs(now.timestamp()))
        after, remaining = before, pending
        if pending:
            # Vercel's scheduled run and its continuations work against a time budget; GitHub's
            # follow-up and owner refreshes take bounded batches.
            budgeted = expected_slot is not None or continuation
            refresh_sources(store, source, source_ids=pending, scheduled=scheduled,
                            maximum=None if budgeted else 64,
                            deadline=time.monotonic() + SWEEP_RUN_SECONDS if budgeted else None, window=window)
            after = store.source_state(include_archive=False)
            attempts = store.feed_attempts(slot)
            now = datetime.now(timezone.utc)
            remaining, deferred = sweep_plan(after, scheduled, now, attempts=attempts, source_ids=source_ids,
                                             host_backoffs=store.feed_host_backoffs(now.timestamp()))

        checked = {ident for ident in pending if (after.get(ident, {}).get("checked") or 0) >= scheduled.timestamp()}
        if checked and not remaining and not owner and not priority:
            store.prune()
        if pending and not checked and now < closes:
            raise HTTPException(503, "The feed refresh batch made no progress.")
        failures = [{"id": ident, "label": BY_ID[ident].label, "reason": after[ident].get("error") or "unknown"}
                    for ident in sorted(checked) if after[ident]["available"] is False
                    or (after[ident].get("retry_at") or 0) > now.timestamp()]
        result = {"status": "refreshed" if checked else "complete", "checked": len(checked),
                  "healthy": sum(after[ident]["available"] is True for ident in checked), "failures": failures,
                  "remaining": len(remaining), "deferred": len(deferred)}
        if not remaining or now >= closes or expected_slot is not None:
            interrupted = {ident for ident in attempts if (source_ids is None or ident in source_ids)
                           and (after.get(ident, {}).get("checked") or 0) < scheduled.timestamp()}
            result["unconfirmed"] = sorted(interrupted)
            if remaining:
                result["unfinished"] = sorted(remaining)
            result["deferrals"] = [{"id": ident, "label": BY_ID[ident].label,
                "retry_at": datetime.fromtimestamp(deferred[ident], timezone.utc).isoformat()} for ident in sorted(deferred)]
            result["scheduled_at"] = next_sweep
            if remaining and now >= closes:
                result["status"] = "closed"
        return result
    finally:
        store.finish_refresh(lease)


@app.post("/api/admin/refresh")
def refresh_admin(batch: SourceRefresh | None = None, source: str | None = None, authorization: str | None = Header(default=None)):
    require_owner(authorization)
    if source and source not in BY_ID:
        raise HTTPException(404, "Unknown source.")
    if source and batch:
        raise HTTPException(422, "Choose one source or a source batch.")
    selected = {source} if source else set(batch.source_ids) if batch else None
    return {**run_sweep(source=source, source_ids=selected, owner=True), "sources": source_catalog(source_store())}


@app.get("/api/news")
def news(request: Request, response: Response, background: BackgroundTasks,
         hours: TimeWindow = TimeWindow.week, source: str = "all",
         force: bool = False, region: Annotated[str, Query(max_length=16)] = "",
         q: Annotated[str, Query(max_length=150)] = "", kind: str = "all", publisher: str = "", topic: str = "all",
         sort: SortOrder = "latest", coverage: Annotated[str, Query(max_length=24)] = "",
         language: Annotated[str, Query(max_length=16)] = "",
         subject: Annotated[str, Query(max_length=24)] = "",
         limit: Annotated[int, Query(ge=1, le=50)] = 24, cursor: Annotated[str | None, Query(max_length=320)] = None):
    if (source not in ("all", *GROUPS) and source not in BY_ID) or kind not in KINDS or (publisher and publisher not in BY_ID):
        raise HTTPException(422, "Choose a supported source or content type.")
    if topic != "all" and topic not in TOPICS:
        raise HTTPException(422, "Choose a supported topic.")
    if subject and subject not in SUBJECTS:
        raise HTTPException(422, "Choose a supported subject.")
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
                           language=language, subject=subject)
            key = hashlib.sha256(json.dumps([str(store.engine.url), filters], sort_keys=True).encode()).hexdigest()
            # Reuse common views. Arbitrary search terms and cursors stay out of shared Redis.
            cacheable = not q and not cursor
            edge_cacheable = (cacheable and not force and source == "all" and kind == "all" and not publisher
                              and not region and not coverage and not language and not subject and sort == "latest" and limit in (12, 24)
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
            if edge_cacheable and result["freshness"]["counts"]["fresh"]:
                response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
                response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=30, stale-while-revalidate=30"
            return result

        fingerprint = page_fingerprint(hours, source, q, kind, publisher, topic, region, sort, coverage, language, subject)
        ranked = sort == "relevance" and bool(q)
        now, marker = page_window(cursor, fingerprint, ranked=ranked)
        payload = collect_news()
        if cursor is None:
            now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        matching = [a for a in payload["articles"] if cutoff <= datetime.fromisoformat(a["published_at"]) <= now
                    and (kind == "all" or a.get("kind") == kind)
                    and (not coverage or (entry := BY_ID.get(a.get("source_id"))) and entry.coverage == coverage)
                    and (not subject or subject in subjects_for(a))
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
        raise HTTPException(502, "Could not prepare this brief. Please try again shortly.") from None
    expires = int(time.time()) + 3600
    preview_id = secrets.token_urlsafe(24) if store else None
    if store:
        store.save_preview(preview_id, digest, expires)
    return {"digest": digest, "expires": expires, "signature": signature(digest, expires), "preview_id": preview_id,
            "source_basis": "The brief uses publisher feed titles and excerpts."}, hit


def prepare_digest(body, store, name, focus, world, progress):
    if progress:
        progress(1)
    scope = [label for label in (TOPICS.get(body.topic), REGION_LABELS.get(body.region), LANGUAGES.get(body.language),
                                 COVERAGE_TYPES.get(body.coverage), SUBJECTS.get(body.subject)) if label]
    if not world and not focus:
        focus = ", ".join(scope)
    if store:
        filters = {"topic": body.topic, "region": body.region, "language": body.language, "coverage": body.coverage,
                   "subject": body.subject}
        available = (store.world_candidates(body.hours, body.sources, **filters) if world else
                     store.candidates(body.hours, body.sources, search_terms(focus), **filters))
        pins = store.pinned_articles(body.pinned_ids)
        found = {article["id"] for article in pins}
        pins.extend(article for ident in body.pinned_ids if ident not in found
                    and (article := curiosity_article(ident) or saved_curiosity_article(store, ident)) is not None)
    else:
        archive = collect_news()["articles"]
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=body.hours)
        available = [article for article in archive if cutoff <= datetime.fromisoformat(article["published_at"]) <= now
                     and (body.topic == "all" or topic_for(article) == body.topic)
                     and (not body.subject or body.subject in subjects_for(article))
                     and region_matches(article, body.region)
                     and (not body.language or BY_ID.get(article.get("source_id"))
                          and BY_ID[article["source_id"]].language == body.language)
                     and (not body.coverage or (source := article_source(article)) and source.coverage == body.coverage)]
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
        return build_world([public_article(article) for article in selected], body.hours, all_pool=pool,
                           scope=scope, includes_pins=bool(pins))
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
    if body.expires < time.time() or not hmac.compare_digest(body.signature.encode(), signature(body.digest, body.expires).encode()):
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
        send_email(BRIEF_SUBJECT, body.digest["markdown"], body.digest["html"], recipients=[os.environ["MY_EMAIL"]])
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
