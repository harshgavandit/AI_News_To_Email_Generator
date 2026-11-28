"""Owner-only editorial review and reversible archive writes."""

import json
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update

from app import editor_store as db, event_intelligence, guardrails, research
from app.coverage import REGION_LABELS, TOPICS
from app.launch_store import articles, sources
from app.monitoring import begin_write
from app.sources import BY_ID, LANGUAGES

router = APIRouter(prefix="/api/admin/editor")
BULK_CONFIDENCE = 0.92
IDENTIFIER = r"^[a-f0-9]{64}$"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoteLine(Input):
    story_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=8, max_length=240)


class Edit(Input):
    topic: str | None = Field(default=None, max_length=32)
    region: str | None = Field(default=None, max_length=16)
    language: str | None = Field(default=None, max_length=12)
    anchor: str | None = Field(default=None, max_length=40)
    operation: Literal["review", "pause"] | None = None
    note: list[NoteLine] | None = Field(default=None, min_length=3, max_length=5)
    pitch: str | None = Field(default=None, min_length=8, max_length=240)
    hide_reason: str | None = Field(default=None, min_length=8, max_length=240)


class Decision(Input):
    revision: int = Field(ge=0, le=1_000_000)
    action: Literal["approve", "reject", "snooze", "undo"]
    edit: Edit | None = None
    snooze_hours: int = Field(default=24, ge=1, le=720)


class Bulk(Input):
    items: dict[str, int] = Field(min_length=1, max_length=10)


def owner_store(authorization, response):
    from app.server import require_owner, source_store

    require_owner(
        authorization,
        detail="Enter a valid owner access key to review editorial suggestions.",
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vercel-CDN-Cache-Control"] = "no-store"
    store = source_store()
    db.ensure(store)
    return store


def present(row, now):
    status = (
        "pending"
        if row["status"] == "snoozed" and row["snoozed_until"] <= now
        else row["status"]
    )
    return {
        **json.loads(row["payload"]),
        "status": status,
        "created": row["created"],
        "snoozed_until": row["snoozed_until"],
        "revision": row["revision"],
    }


@router.get("")
def get_queue(
    response: Response,
    authorization: str | None = Header(default=None),
    kind: Literal[
        "all", "duplicate", "labels", "hide", "source", "recap", "curiosity"
    ] = "all",
    status: Literal[
        "pending", "snoozed", "approved", "rejected", "undone", "all"
    ] = "pending",
    minimum: float = Query(default=0, ge=0, le=1),
    days: int = Query(default=30, ge=1, le=3650),
    offset: int = Query(default=0, ge=0, le=100_000),
    activity_offset: int = Query(default=0, ge=0, le=10_000_000),
):
    store = owner_store(authorization, response)
    now = time.time()
    filters = [
        db.queue.c.confidence >= minimum,
        db.queue.c.created >= now - days * 86400,
    ]
    if kind != "all":
        filters.append(db.queue.c.kind == kind)
    if status == "pending":
        filters.append(db.pending_clause(now))
    elif status == "snoozed":
        filters.extend([db.queue.c.status == "snoozed", db.queue.c.snoozed_until > now])
    elif status != "all":
        filters.append(db.queue.c.status == status)
    with store.engine.connect() as conn:
        pending = conn.scalar(
            select(func.count()).select_from(db.queue).where(db.pending_clause(now))
        )
        rows = (
            conn.execute(
                select(db.queue)
                .where(*filters)
                .order_by(db.queue.c.created.desc(), db.queue.c.id)
                .offset(offset)
                .limit(51)
            )
            .mappings()
            .all()
        )
        log = conn.execute(
            select(
                db.activity.c.id,
                db.activity.c.action,
                db.activity.c.created,
                db.activity.c.details,
                db.queue.c.kind,
                db.queue.c.revision,
                db.queue.c.status,
                db.queue.c.id.label("suggestion_id"),
                db.queue.c.payload,
            )
            .join(db.queue, db.queue.c.id == db.activity.c.suggestion_id)
            .order_by(db.activity.c.created.desc(), db.activity.c.id)
            .offset(activity_offset)
            .limit(81)
        ).mappings()
        activity = []
        for row in log:
            entry = dict(row)
            original = json.loads(entry.pop("payload"))
            entry["target"] = original["action"].get("week") or " / ".join(
                record["title"] for record in original["evidence"][:2]
            )
            entry["details"] = json.loads(row["details"]) if row["details"] else None
            activity.append(entry)
    return {
        "pending": pending,
        "items": [present(row, now) for row in rows[:50]],
        "more": len(rows) > 50,
        "activity": activity[:80],
        "more_activity": len(activity) > 80,
        "bulk_confidence": BULK_CONFIDENCE,
        "options": {"topics": TOPICS, "regions": REGION_LABELS, "languages": LANGUAGES},
    }


def safe_note(text):
    return research.safe_prose(text, 240) and not any(
        pattern.search(text)
        for pattern in (guardrails.URLS, guardrails.PERSONAL, guardrails.INJECTION)
    )


def edited_payload(item, edit):
    action = item["action"].copy()
    values = edit.model_dump(exclude_none=True) if edit else {}
    kind = item["kind"]
    allowed = {
        "duplicate": {"anchor"},
        "labels": {"topic", "region", "language"},
        "hide": {"hide_reason"},
        "source": {"operation"},
        "recap": {"note"},
        "curiosity": {"pitch"},
    }[kind]
    if set(values) - allowed:
        raise ValueError("These edits do not apply to this suggestion.")
    if kind == "labels" and values:
        for key, choices in (
            ("topic", TOPICS),
            ("region", REGION_LABELS),
            ("language", LANGUAGES),
        ):
            if key in values and values[key] not in choices:
                raise ValueError("Choose a supported classification.")
        action["labels"] = {**action["labels"], **values}
    elif kind == "duplicate" and values:
        ids = action["stories"]
        if values["anchor"] not in ids:
            raise ValueError("Choose one of the cited stories as the anchor.")
        action["stories"] = [
            values["anchor"],
            next(ident for ident in ids if ident != values["anchor"]),
        ]
    else:
        action.update(values)
    if action.get("hide_reason") and not safe_note(action["hide_reason"]):
        raise ValueError("Use a plain text note without links or private details.")
    return action


def lock_story(conn, ident):
    row = (
        conn.execute(select(articles).where(articles.c.id == ident).with_for_update())
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError("A cited story is no longer in the archive.")
    return dict(row)


def recap_note(item, action):
    rows = {row["id"]: row for row in item["evidence"]}
    lines = []
    seen = set()
    for line in action["note"]:
        if (
            line["story_id"] not in rows
            or line["story_id"] in seen
            or not safe_note(line["text"])
        ):
            raise ValueError(
                "Each note line needs a different cited archive story and plain text."
            )
        seen.add(line["story_id"])
        row = rows[line["story_id"]]
        lines.append(
            {
                "text": line["text"],
                "url": row["url"],
                "title": row["title"],
                "publisher": row["publisher"],
            }
        )
    return lines


def apply(store, conn, item, action, now):
    kind = item["kind"]
    if kind in ("labels", "hide"):
        ident = action["story_id"]
        row = lock_story(conn, ident)
        values = (
            {"editor_hidden": True}
            if kind == "hide"
            else {f"editor_{key}": value for key, value in action["labels"].items()}
        )
        conn.execute(update(articles).where(articles.c.id == ident).values(**values))
        return {
            "story_id": ident,
            "before": {key: row[key] for key in values},
            "after": values,
        }
    if kind == "duplicate":
        # Lock articles in stable order even if the owner changes which story is the anchor.
        records = {
            ident: lock_story(conn, ident) for ident in sorted(action["stories"])
        }
        if any(row["editor_hidden"] for row in records.values()):
            raise ValueError(
                "A cited story is hidden. Review the stories before merging."
            )
        return {
            "merge": event_intelligence.merge_reviewed(
                store, conn, [records[ident] for ident in action["stories"]], now
            )
        }
    if kind == "source" and action["operation"] == "pause":
        ident = action["source_id"]
        if ident not in BY_ID:
            raise ValueError("This source is no longer registered.")
        before = conn.scalar(
            select(sources.c.enabled).where(sources.c.id == ident).with_for_update()
        )
        if before is None:
            raise ValueError("This source no longer has a health record.")
        store.enable(ident, False, conn=conn)
        return {"source": ident, "before": before}
    if kind == "recap":
        lines = json.dumps(recap_note(item, action), ensure_ascii=False)
        week = action["week"]
        previous = conn.scalar(
            select(db.recap_notes.c.note)
            .where(db.recap_notes.c.week == week)
            .with_for_update()
        )
        stmt = store.insert(db.recap_notes).values(week=week, note=lines)
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[db.recap_notes.c.week], set_={"note": lines}
            )
        )
        return {"week": week, "before": previous, "after": lines}
    if kind == "curiosity":
        lock_story(conn, action["story_id"])
        if action.get("pitch") and not safe_note(action["pitch"]):
            raise ValueError("Use a plain text pitch without links or private details.")
    # Source review and Curiosity approval are private acknowledgements.
    return {}


def undo(store, conn, item, receipt, now):
    if "story_id" in receipt:
        ident = receipt["story_id"]
        current = lock_story(conn, ident)
        if any(current[key] != value for key, value in receipt["after"].items()):
            raise ValueError("A later decision changed these fields. Undo it first.")
        conn.execute(
            update(articles).where(articles.c.id == ident).values(**receipt["before"])
        )
    elif receipt.get("merge"):
        event_intelligence.undo_reviewed_merge(store, conn, receipt["merge"], now)
    elif "source" in receipt:
        ident = receipt["source"]
        if receipt["before"] and (ident not in BY_ID or not BY_ID[ident].enabled):
            raise ValueError("The current catalog has disabled this integration.")
        current = conn.scalar(
            select(sources.c.enabled).where(sources.c.id == ident).with_for_update()
        )
        if current is not False:
            raise ValueError("This source already changed after the decision.")
        store.enable(ident, receipt["before"], conn=conn)
    elif "week" in receipt:
        table = db.recap_notes
        target = table.c.week == receipt["week"]
        current = conn.scalar(select(table.c.note).where(target).with_for_update())
        if current != receipt["after"]:
            raise ValueError("A later decision changed this note. Undo it first.")
        if receipt["before"] is None:
            conn.execute(delete(table).where(target))
        else:
            conn.execute(update(table).where(target).values(note=receipt["before"]))


def decide(store, conn, ident, body, now, *, bulk=False):
    row = (
        conn.execute(select(db.queue).where(db.queue.c.id == ident).with_for_update())
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "This suggestion is unavailable.")
    if row["revision"] != body.revision:
        raise HTTPException(409, "The suggestion changed. Reload the review queue.")
    if bulk and (
        row["kind"] != "duplicate"
        or row["confidence"] < BULK_CONFIDENCE
        or row["status"] != "pending"
    ):
        raise HTTPException(
            409, "Bulk approval requires pending high-confidence duplicates."
        )
    item = json.loads(row["payload"])
    receipt, details, snoozed = None, None, None
    if body.edit is not None and body.action != "approve":
        raise ValueError("Edits are applied with approval.")
    if body.action == "undo":
        if row["status"] != "approved":
            raise HTTPException(409, "Only an approved decision can be undone.")
        saved = conn.scalar(
            select(db.activity.c.receipt)
            .where(
                db.activity.c.suggestion_id == ident, db.activity.c.action == "approve"
            )
            .order_by(db.activity.c.created.desc())
            .limit(1)
        )
        if saved is None:
            raise HTTPException(409, "The approval receipt is unavailable.")
        undo(store, conn, item, json.loads(saved), now)
        status = "undone"
    else:
        if row["status"] not in ("pending", "snoozed"):
            raise HTTPException(409, "This suggestion has already been reviewed.")
        status = {"approve": "approved", "reject": "rejected", "snooze": "snoozed"}[
            body.action
        ]
        if body.action == "approve":
            action = edited_payload(item, body.edit)
            receipt = json.dumps(apply(store, conn, item, action, now))
            details = action
        elif body.action == "snooze":
            snoozed = now + body.snooze_hours * 3600
            details = {"snoozed_until": snoozed}
    conn.execute(
        update(db.queue)
        .where(db.queue.c.id == ident)
        .values(status=status, snoozed_until=snoozed, revision=row["revision"] + 1)
    )
    conn.execute(
        db.activity.insert().values(
            id=secrets.token_hex(16),
            suggestion_id=ident,
            action=body.action,
            created=now,
            receipt=receipt,
            details=json.dumps(details) if details else None,
        )
    )
    return {"id": ident, "status": status, "revision": row["revision"] + 1}


def change(store, items, *, bulk=False):
    store.ensure_discovery_schema()
    try:
        with store.engine.begin() as conn:
            begin_write(conn)
            if conn.dialect.name == "postgresql":
                # Serialize owner actions across different suggestions that may target the same event.
                conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108837)")
            now = time.time()
            return [
                decide(store, conn, ident, body, now, bulk=bulk)
                for ident, body in items
            ]
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/bulk")
def bulk_approve(
    body: Bulk, response: Response, authorization: str | None = Header(default=None)
):
    import re

    store = owner_store(authorization, response)
    if any(
        not re.fullmatch(IDENTIFIER, ident) or not 0 <= revision <= 1_000_000
        for ident, revision in body.items.items()
    ):
        raise HTTPException(422, "Supply valid suggestion IDs and revisions.")
    return {
        "items": change(
            store,
            [
                (ident, Decision(revision=revision, action="approve"))
                for ident, revision in sorted(body.items.items())
            ],
            bulk=True,
        )
    }


@router.post("/{ident}")
def review_item(
    body: Decision,
    response: Response,
    ident: str = Path(pattern=IDENTIFIER),
    authorization: str | None = Header(default=None),
):
    return change(owner_store(authorization, response), [(ident, body)])[0]
