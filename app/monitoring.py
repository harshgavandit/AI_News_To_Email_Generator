"""Durable, browser-isolated watches evaluated by the scheduled intelligence worker."""
from datetime import UTC, datetime
import hashlib
import json
import os
import re
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, inspect, select, update

from app.coverage import TOPICS
from app.discovery import search_terms
from app.launch_store import monitor_alerts, monitor_profiles, monitor_watches
from app.research import watch_matches


router = APIRouter(prefix="/api/intelligence/inbox")
COOKIE = "informa_monitor"
COOKIE_PATH = "/api/intelligence/inbox"
INACTIVITY = 30 * 86400
RETENTION = 14 * 86400
INTERVAL = 300
MAX_ALERTS = 60
COOKIE_TOKEN = re.compile(r"[0-9a-f]{64}\Z")


class Watch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    query: str = Field(min_length=2, max_length=150)
    topic: str = Field(default="all", max_length=24)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.topic not in ("all", *TOPICS) or not search_terms(self.query):
            raise ValueError("Choose a topic and enter words to watch.")
        return self


class WatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    watches: list[Watch] = Field(max_length=6)

    @model_validator(mode="after")
    def unique_watches(self):
        if len({watch.id for watch in self.watches}) != len(self.watches) or len({
            (search_terms(watch.query), watch.topic) for watch in self.watches
        }) != len(self.watches):
            raise ValueError("Each watch must be unique.")
        return self


class WatchUpdate(WatchList):
    revision: int = Field(ge=0, le=2_000_000_000)


def schema_ready(store):
    if getattr(store, "_monitor_schema_ready", False):
        return True
    with store.engine.connect() as conn:
        known = inspect(conn)
        store._monitor_schema_ready = all(known.has_table(table.name) for table in (
            monitor_profiles, monitor_watches, monitor_alerts))
    return store._monitor_schema_ready


def configured_store(*, required=True):
    from app.server import get_store

    store = get_store()
    if store and schema_ready(store):
        return store
    if required:
        raise HTTPException(503, "Background monitoring is temporarily unavailable. Browser watches can still run here.")
    return None


def profile_id(request):
    token = request.cookies.get(COOKIE, "")
    return hashlib.sha256(token.encode()).hexdigest() if COOKIE_TOKEN.fullmatch(token) else None


def protect_write(request):
    origin = request.headers.get("origin")
    public_origin = os.getenv("PUBLIC_ORIGIN", "").rstrip("/")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin and origin not in {str(request.base_url).rstrip("/"), public_origin}
    ):
        raise HTTPException(403, "Open the Research Desk in this browser to manage monitoring.")


def begin_write(conn):
    if conn.dialect.name == "sqlite":
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def active_profile(conn, ident, now, *, lock=False):
    if not ident:
        return None
    stmt = select(monitor_profiles).where(monitor_profiles.c.id == ident, monitor_profiles.c.expires > now)
    return conn.execute(stmt.with_for_update() if lock else stmt).mappings().first()


def watch_values(ident, watch, now):
    return {"profile_id": ident, **watch.model_dump(), "created": now, "next_check": now, "checked": None}


def snapshot(store, ident, now):
    with store.engine.connect() as conn:
        profile = active_profile(conn, ident, now)
        if not profile:
            return {"available": True, "active": False, "watches": [], "alerts": [], "unread": 0}
        watches = conn.execute(select(monitor_watches).where(monitor_watches.c.profile_id == ident)
                               .order_by(monitor_watches.c.created, monitor_watches.c.id)).mappings()
        alerts = conn.execute(select(monitor_alerts).where(monitor_alerts.c.profile_id == ident,
            monitor_alerts.c.created >= now - RETENTION).order_by(monitor_alerts.c.updated.desc(),
            monitor_alerts.c.id.desc()).limit(MAX_ALERTS)).mappings()
        alert_rows = [{"id": row["id"], "watch_id": row["watch_id"], "created": row["created"],
                       "updated": row["updated"], "unread": row["read_at"] is None,
                       "sources": json.loads(row["evidence"])} for row in alerts]
        watch_rows = [{key: row[key] for key in ("id", "query", "topic", "checked")} for row in watches]
        return {"available": True, "active": True, "revision": profile["revision"], "watches": watch_rows,
                "alerts": alert_rows, "unread": sum(row["unread"] for row in alert_rows)}


def set_cookie(response, request, token):
    response.set_cookie(COOKIE, token, max_age=INACTIVITY, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https" or bool(os.getenv("VERCEL")), path=COOKIE_PATH)


@router.get("")
def inbox(request: Request, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    store = configured_store(required=False)
    if not store:
        return {"available": False, "active": False, "watches": [], "alerts": [], "unread": 0}
    ident, now = profile_id(request), time.time()
    if ident:
        with store.engine.begin() as conn:
            renewed = conn.execute(update(monitor_profiles).where(
                monitor_profiles.c.id == ident, monitor_profiles.c.expires > now,
                monitor_profiles.c.expires < now + INACTIVITY - 86400).values(expires=now + INACTIVITY)).rowcount
        if renewed:
            set_cookie(response, request, request.cookies[COOKIE])
    return snapshot(store, ident, now)


@router.post("/enable", status_code=201)
def enable(body: WatchList, request: Request, response: Response):
    from app.server import admit_expensive

    protect_write(request)
    store = configured_store()
    prior, now = profile_id(request), time.time()
    if prior:
        prior_state = snapshot(store, prior, now)
        if prior_state["active"]:
            response.headers["Cache-Control"] = "private, no-store"
            return prior_state
    admit_expensive(store, request, "monitor-creation", 5, 3600)
    if not store.admit([("monitor-creation-total", datetime.now(UTC).date().isoformat(), 3000)]):
        raise HTTPException(429, "Background monitoring sign-ups are at capacity. Try again tomorrow.")
    token = secrets.token_hex(32)
    ident = hashlib.sha256(token.encode()).hexdigest()
    with store.engine.begin() as conn:
        conn.execute(monitor_profiles.insert().values(id=ident, expires=now + INACTIVITY, revision=0))
        if body.watches:
            conn.execute(monitor_watches.insert(), [watch_values(ident, watch, now) for watch in body.watches])
    set_cookie(response, request, token)
    response.headers["Cache-Control"] = "private, no-store"
    return snapshot(store, ident, now)


@router.put("/watches")
def save_watches(body: WatchUpdate, request: Request, response: Response):
    from app.server import admit_expensive

    protect_write(request)
    store, ident, now = configured_store(), profile_id(request), time.time()
    if not ident:
        raise HTTPException(401, "Enable background monitoring in this browser first.")
    admit_expensive(store, request, "monitor-edit", 20, 60)
    with store.engine.begin() as conn:
        begin_write(conn)
        profile = active_profile(conn, ident, now, lock=True)
        if not profile:
            raise HTTPException(401, "Enable background monitoring in this browser first.")
        if profile["revision"] != body.revision:
            raise HTTPException(409, "The watches changed in another tab. Reload this list before editing.")
        prior = {row["id"]: row for row in conn.execute(select(monitor_watches).where(
            monitor_watches.c.profile_id == ident)).mappings()}
        stable = {watch.id for watch in body.watches if watch.id in prior and
                  (watch.query, watch.topic) == (prior[watch.id]["query"], prior[watch.id]["topic"])}
        removed = set(prior) - stable
        if removed:
            conn.execute(delete(monitor_watches).where(monitor_watches.c.profile_id == ident,
                                                       monitor_watches.c.id.in_(removed)))
            conn.execute(delete(monitor_alerts).where(monitor_alerts.c.profile_id == ident,
                                                     monitor_alerts.c.watch_id.in_(removed)))
        additions = [watch_values(ident, watch, now) for watch in body.watches if watch.id not in stable]
        if additions:
            conn.execute(monitor_watches.insert(), additions)
        conn.execute(update(monitor_profiles).where(monitor_profiles.c.id == ident).values(revision=body.revision + 1))
    response.headers["Cache-Control"] = "private, no-store"
    return snapshot(store, ident, now)


@router.post("/read")
def mark_read(request: Request, response: Response):
    protect_write(request)
    store, ident, now = configured_store(), profile_id(request), time.time()
    with store.engine.begin() as conn:
        begin_write(conn)
        if not active_profile(conn, ident, now, lock=True):
            raise HTTPException(401, "Enable background monitoring in this browser first.")
        conn.execute(update(monitor_alerts).where(monitor_alerts.c.profile_id == ident,
                    monitor_alerts.c.read_at.is_(None)).values(read_at=now))
    response.headers["Cache-Control"] = "private, no-store"
    return snapshot(store, ident, now)


def delete_profiles(conn, ids):
    conn.execute(delete(monitor_watches).where(monitor_watches.c.profile_id.in_(ids)))
    conn.execute(delete(monitor_alerts).where(monitor_alerts.c.profile_id.in_(ids)))
    conn.execute(delete(monitor_profiles).where(monitor_profiles.c.id.in_(ids)))


@router.delete("")
def disable(request: Request, response: Response):
    protect_write(request)
    ident = profile_id(request)
    if ident:
        with configured_store().engine.begin() as conn:
            begin_write(conn)
            if conn.execute(select(monitor_profiles.c.id).where(
                monitor_profiles.c.id == ident).with_for_update()).first():
                delete_profiles(conn, [ident])
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.headers["Cache-Control"] = "private, no-store"
    return {"active": False}


def persist_matches(store, watch, matches, now):
    ident, watch_id = watch["profile_id"], watch["id"]
    evidence = {row["id"]: row for row in matches["evidence"]}
    filters = (monitor_alerts.c.profile_id == ident, monitor_alerts.c.watch_id == watch_id,
               monitor_alerts.c.created >= now - RETENTION)
    created = 0
    with store.engine.begin() as conn:
        begin_write(conn)
        current = conn.execute(select(monitor_watches).where(
            monitor_watches.c.profile_id == ident, monitor_watches.c.id == watch_id).with_for_update()).mappings().first()
        if not current or current["created"] != watch["created"]:
            return 0
        existing = [(row.id, json.loads(row.evidence)) for row in conn.execute(select(
            monitor_alerts.c.id, monitor_alerts.c.evidence).where(*filters)
            .order_by(monitor_alerts.c.created, monitor_alerts.c.id))]
        # A second publication can extend an existing alert without adding an unread duplicate.
        for cluster in matches["clusters"]:
            sources = [{key: evidence[article_id][key] for key in ("id", "title", "publisher", "url", "published_at")}
                       for article_id in cluster["article_ids"]]
            ids = {row["id"] for row in sources}
            linked = next(((alert_id, rows) for alert_id, rows in existing
                           if ids.intersection(row["id"] for row in rows)), None)
            if linked:
                alert_id, previous = linked
                known = {row["id"] for row in previous}
                new_sources = [row for row in sources if row["id"] not in known][:max(0, 10 - len(previous))]
                if new_sources:
                    previous.extend(new_sources)
                    conn.execute(update(monitor_alerts).where(monitor_alerts.c.id == alert_id)
                                 .values(updated=now, evidence=json.dumps(previous, ensure_ascii=False)))
                continue
            if all(datetime.fromisoformat(row["published_at"]).timestamp() < watch["created"] for row in sources):
                continue
            alert_id = secrets.token_hex(16)
            conn.execute(monitor_alerts.insert().values(id=alert_id, profile_id=ident, watch_id=watch_id,
                created=now, updated=now, evidence=json.dumps(sources, ensure_ascii=False)))
            existing.append((alert_id, sources))
            created += 1
        obsolete = select(monitor_alerts.c.id).where(monitor_alerts.c.profile_id == ident).order_by(
            monitor_alerts.c.updated.desc(), monitor_alerts.c.id.desc()).offset(MAX_ALERTS).limit(12)
        conn.execute(delete(monitor_alerts).where(monitor_alerts.c.id.in_(obsolete)))
        conn.execute(update(monitor_watches).where(monitor_watches.c.profile_id == ident,
                     monitor_watches.c.id == watch_id).values(checked=now, next_check=now + INTERVAL))
    return created


def run_monitoring(store, *, now=None):
    """Process due watches with a bounded batch and no network or model calls."""
    if not schema_ready(store):
        return {"monitoring_status": "migration_required", "watches_checked": 0, "alerts_created": 0}
    now = time.time() if now is None else now
    with store.engine.begin() as conn:
        begin_write(conn)
        expired = conn.scalars(select(monitor_profiles.c.id).where(monitor_profiles.c.expires <= now)
                               .order_by(monitor_profiles.c.expires).limit(100).with_for_update()).all()
        if expired:
            delete_profiles(conn, expired)
        old_alerts = select(monitor_alerts.c.id).where(monitor_alerts.c.created < now - RETENTION).limit(400)
        conn.execute(delete(monitor_alerts).where(monitor_alerts.c.id.in_(old_alerts)))
        due = conn.execute(select(monitor_watches).join(monitor_profiles,
            monitor_profiles.c.id == monitor_watches.c.profile_id).where(monitor_profiles.c.expires > now,
            monitor_watches.c.next_check <= now).order_by(monitor_watches.c.next_check,
            monitor_watches.c.profile_id, monitor_watches.c.id).limit(48)).mappings().all()
    known, checked, created = {}, 0, 0
    deadline = time.monotonic() + 30
    for row in due:
        if time.monotonic() >= deadline:
            break
        key = (search_terms(row["query"]), row["topic"])
        if key not in known:
            known[key], = watch_matches(store, [Watch(id=row["id"], query=row["query"], topic=row["topic"])])
        created += persist_matches(store, row, known[key], now)
        checked += 1
    return {"monitoring_status": "checked", "watches_checked": checked, "alerts_created": created}
