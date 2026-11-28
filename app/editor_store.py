"""Private editorial proposals and the owner decision history."""

import json
import time

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    String,
    Table,
    Text,
    func,
    inspect,
    select,
)

from app.launch_store import schema

queue = Table(
    "brief_editor_queue",
    schema,
    Column("id", String(64), primary_key=True),
    Column("kind", String(24), nullable=False),
    Column("payload", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("created", Float, nullable=False),
    Column("status", String(16), nullable=False),
    Column("snoozed_until", Float),
    Column("revision", Integer, nullable=False),
)
Index("brief_editor_queue_status_date", queue.c.status, queue.c.created, queue.c.id)
cursors = Table(
    "brief_editor_cursors",
    schema,
    Column("stream", String(16), primary_key=True),
    Column("stamp", Float, nullable=False),
    Column("marker", String(64), nullable=False),
)
activity = Table(
    "brief_editor_activity",
    schema,
    Column("id", String(32), primary_key=True),
    Column("suggestion_id", String(64), nullable=False),
    Column("action", String(20), nullable=False),
    Column("created", Float, nullable=False, index=True),
    Column("receipt", Text),
    Column("details", Text),
)
recap_notes = Table(
    "brief_editor_recap_notes",
    schema,
    Column("week", String(10), primary_key=True),
    Column("note", Text, nullable=False),
)
TABLES = (queue, cursors, activity, recap_notes)


def ensure(store):
    if getattr(store, "_editor_ready", False):
        return
    with store._schema_lock, store.engine.begin() as conn:
        if getattr(store, "_editor_ready", False):
            return
        if not all(inspect(conn).has_table(table.name) for table in TABLES):
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
            else:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            for table in TABLES:
                table.create(conn, checkfirst=True)
    store._editor_ready = True


def pending_clause(now):
    return (queue.c.status == "pending") | (
        (queue.c.status == "snoozed") & (queue.c.snoozed_until <= now)
    )


def pending_count(store):
    ensure(store)
    with store.engine.connect() as conn:
        return (
            conn.scalar(
                select(func.count())
                .select_from(queue)
                .where(pending_clause(time.time()))
            )
            or 0
        )


def existing(conn, identifiers):
    if not identifiers:
        return set()
    return set(conn.scalars(select(queue.c.id).where(queue.c.id.in_(identifiers))))


def cursor(conn, stream, default):
    row = conn.execute(
        select(cursors.c.stamp, cursors.c.marker).where(cursors.c.stream == stream)
    ).first()
    return (row.stamp, row.marker) if row else (default, "")


def queue_batch(store, suggestions, checkpoints, now):
    if not suggestions and not checkpoints:
        return 0
    with store.engine.begin() as conn:
        count = 0
        if suggestions:
            stmt = store.insert(queue).values(
                [
                    {
                        "id": item["id"],
                        "kind": item["kind"],
                        "payload": json.dumps(item),
                        "confidence": item["confidence"],
                        "created": now,
                        "status": "pending",
                        "revision": 0,
                    }
                    for item in suggestions
                ]
            )
            count = len(
                conn.scalars(stmt.on_conflict_do_nothing().returning(queue.c.id)).all()
            )
        for stream, (stamp, marker) in checkpoints.items():
            stmt = store.insert(cursors).values(
                stream=stream, stamp=stamp, marker=marker
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=[cursors.c.stream],
                    set_={"stamp": stamp, "marker": marker},
                    where=(cursors.c.stamp < stamp)
                    | ((cursors.c.stamp == stamp) & (cursors.c.marker < marker)),
                )
            )
    return count


def approved_note(store, week):
    ensure(store)
    with store.engine.connect() as conn:
        payload = conn.scalar(
            select(recap_notes.c.note).where(recap_notes.c.week == week)
        )
    return json.loads(payload) if payload else None
