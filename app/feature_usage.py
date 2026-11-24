"""Anonymous feature usage counts, so the owner can see whether a feature is worth promoting.

Only daily totals per (feature, action) are stored: no reader, IP, browser, story or question text.
Browsers send counts only with audience analytics turned on and no Global Privacy Control or Do Not
Track signal; the server also ignores requests carrying those signals.
"""
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Integer, String, Table, func, inspect, select

from app.launch_store import get_store, schema

router = APIRouter()
feature_usage = Table("brief_feature_usage", schema,
    Column("day", String(10), primary_key=True), Column("feature", String(32), primary_key=True),
    Column("action", String(24), primary_key=True), Column("count", Integer, nullable=False))

# Every countable (feature, action). Anything else is ignored.
FEATURES = {
    "story_dossier": {"open"},
    "story_ask": {"open", "question", "answered", "unanswered", "error"},
}


class UsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature: Literal[tuple(FEATURES)]
    action: str = Field(max_length=24)


class UsageEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[UsageEvent] = Field(max_length=20)


def ensure(store):
    if getattr(store, "_feature_usage_ready", False):
        return
    with store.engine.begin() as conn:
        if not inspect(conn).has_table(feature_usage.name):
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
            feature_usage.create(conn, checkfirst=True)
    store._feature_usage_ready = True


def record(store, events, day=None):
    totals = {}
    for event in events:
        if event.action in FEATURES.get(event.feature, ()):
            totals[(event.feature, event.action)] = totals.get((event.feature, event.action), 0) + 1
    if not totals:
        return 0
    ensure(store)
    day = day or datetime.now(UTC).date().isoformat()
    with store.engine.begin() as conn:
        for (feature, action), count in sorted(totals.items()):
            statement = store.insert(feature_usage).values(day=day, feature=feature, action=action, count=count)
            conn.execute(statement.on_conflict_do_update(
                index_elements=[feature_usage.c.day, feature_usage.c.feature, feature_usage.c.action],
                set_={"count": feature_usage.c.count + statement.excluded.count}))
    return sum(totals.values())


def totals(store, since_day):
    ensure(store)
    with store.engine.connect() as conn:
        rows = conn.execute(select(feature_usage.c.feature, feature_usage.c.action, func.sum(feature_usage.c.count))
                            .where(feature_usage.c.day >= since_day)
                            .group_by(feature_usage.c.feature, feature_usage.c.action)).all()
    return {(feature, action): int(count) for feature, action, count in rows}


@router.post("/api/usage/events", status_code=204)
def record_usage(request: Request, body: UsageEvents):
    from app.server import rate_limit
    if request.headers.get("sec-gpc") == "1" or request.headers.get("dnt") == "1":
        return Response(status_code=204)
    rate_limit(request, "feature-usage", 60)
    store = get_store()
    if store:
        record(store, body.events)
    return Response(status_code=204)
