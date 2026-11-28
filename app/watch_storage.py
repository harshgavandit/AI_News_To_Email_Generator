"""Extensions to the existing anonymous monitor and alert records."""

from datetime import UTC, datetime
import json
import secrets
import time
from typing import TypedDict

from sqlalchemy import (
    Column,
    Float,
    Index,
    String,
    Table,
    Text,
    delete,
    func,
    inspect,
    or_,
    select,
    tuple_,
    update,
)

from app import event_intelligence, watch_agent
from app.launch_store import (
    articles,
    monitor_alerts,
    monitor_delivery,
    monitor_profiles,
    monitor_watches,
    schema,
)

state = Table(
    "brief_watch_agent_state",
    schema,
    Column("profile_id", String(64), primary_key=True),
    Column("watch_id", String(40), primary_key=True),
    Column("spec", Text, nullable=False),
    Column("status", String(24), nullable=False),
    Column("cursor_at", Float, nullable=False),
    Column("cursor_id", String(40), nullable=False),
)
events = Table(
    "brief_watch_agent_events",
    schema,
    Column("profile_id", String(64), primary_key=True),
    Column("event_key", String(46), primary_key=True),
    Column("watch_id", String(40), nullable=False),
    Column("article_id", String(40), nullable=False),
    Column("created", Float, nullable=False),
)
Index("brief_watch_agent_event_history", events.c.profile_id, events.c.created)
feedback = Table(
    "brief_watch_agent_feedback",
    schema,
    Column("alert_id", String(32), primary_key=True),
    Column("profile_id", String(64), nullable=False),
    Column("watch_id", String(40), nullable=False),
    Column("rating", String(16), nullable=False),
    Column("article_id", String(40), nullable=False),
    Column("updated", Float, nullable=False),
)
Index(
    "brief_watch_agent_feedback_watch",
    feedback.c.profile_id,
    feedback.c.watch_id,
    feedback.c.updated,
)
push_links = Table(
    "brief_watch_agent_push_links",
    schema,
    Column("profile_id", String(64), primary_key=True),
    Column("subscription_id", String(64), nullable=False, unique=True),
    Column("enabled_at", Float, nullable=False),
)
push_receipts = Table(
    "brief_watch_agent_push_receipts",
    schema,
    Column("alert_id", String(32), primary_key=True),
    Column("sent_at", Float, nullable=False),
)

MAX_WATCHES_PER_RUN = 16
MAX_CANDIDATES_PER_RUN = 80
PAGE = 420
RUN_SECONDS = 24.0
ARRIVAL_SETTLE_SECONDS = 30


class RunResult(TypedDict):
    watch_agent_status: str
    watch_agent_checked: int
    watch_agent_alerts: int
    watch_agent_candidates: int
    watch_agent_model_calls: int


def ready(store, conn) -> bool:
    if not getattr(store, "_watch_agent_ready", False):
        inspector = inspect(conn)
        store._watch_agent_ready = inspector.has_table(push_receipts.name)
    return bool(store._watch_agent_ready)


def write_specs(conn, profile: str, watches, now: float):
    values = [
        {
            "profile_id": profile,
            "watch_id": watch.id,
            "spec": watch.agent.model_dump_json(),
            "cursor_at": now,
            "cursor_id": "",
            "status": "waiting",
        }
        for watch in watches
        if watch.agent
    ]
    if values:
        conn.execute(state.insert(), values)


def remove(conn, profiles, watch_ids=None, *, delete_events=True):
    for table in (state, feedback, events) if delete_events else (state, feedback):
        filters = [table.c.profile_id.in_(profiles)]
        if watch_ids is not None:
            filters.append(table.c.watch_id.in_(watch_ids))
        conn.execute(delete(table).where(*filters))
    if watch_ids is None:
        conn.execute(delete(push_links).where(push_links.c.profile_id.in_(profiles)))


def watch_snapshot(conn, profile: str) -> tuple[dict, dict, dict, bool]:
    specs = {
        row.watch_id: (json.loads(row.spec), row.status)
        for row in conn.execute(
            select(state.c.watch_id, state.c.spec, state.c.status).where(
                state.c.profile_id == profile
            )
        )
    }
    ratings = dict(
        conn.execute(
            select(feedback.c.alert_id, feedback.c.rating).where(
                feedback.c.profile_id == profile
            )
        ).all()
    )
    totals: dict[str, dict[str, int]] = {}
    for watch_id, rating, count in conn.execute(
        select(feedback.c.watch_id, feedback.c.rating, func.count())
        .where(feedback.c.profile_id == profile)
        .group_by(feedback.c.watch_id, feedback.c.rating)
    ):
        totals.setdefault(watch_id, {})[rating] = count
    linked = (
        conn.scalar(
            select(push_links.c.profile_id).where(push_links.c.profile_id == profile)
        )
        is not None
    )
    return specs, ratings, totals, linked


def scope(conn, *, with_controls: bool, now: float):
    query = (
        select(monitor_watches, state.c.spec, state.c.cursor_at, state.c.cursor_id)
        .join(
            state,
            (state.c.profile_id == monitor_watches.c.profile_id)
            & (state.c.watch_id == monitor_watches.c.id),
        )
        .join(monitor_profiles, monitor_profiles.c.id == monitor_watches.c.profile_id)
    )
    if with_controls:
        query = query.outerjoin(
            monitor_delivery,
            (monitor_delivery.c.profile_id == monitor_watches.c.profile_id)
            & (monitor_delivery.c.watch_id == monitor_watches.c.id),
        ).where(
            monitor_delivery.c.muted.is_not(True),
            or_(
                monitor_delivery.c.snoozed_until.is_(None),
                monitor_delivery.c.snoozed_until <= now,
            ),
        )
    return (
        conn.execute(
            query.where(
                monitor_watches.c.next_check <= now, monitor_profiles.c.expires > now
            )
            .order_by(
                monitor_watches.c.next_check,
                monitor_watches.c.profile_id,
                monitor_watches.c.id,
            )
            .limit(MAX_WATCHES_PER_RUN)
        )
        .mappings()
        .all()
    )


def archive_batch(store, conn, minimum: tuple[float, str], until: float) -> list[dict]:
    marker = tuple_(articles.c.first_seen, articles.c.id)
    return [
        dict(row)
        for row in conn.execute(
            store.query(90 * 24, now=datetime.fromtimestamp(until, UTC))
            .where(marker > minimum, articles.c.first_seen < until)
            .order_by(articles.c.first_seen, articles.c.id)
            .limit(PAGE + 1)
        ).mappings()
    ]


def negative_examples(conn, watches) -> dict[tuple[str, str], list[dict]]:
    identities = [(row["profile_id"], row["id"]) for row in watches]
    rank = (
        func.row_number()
        .over(
            partition_by=(feedback.c.profile_id, feedback.c.watch_id),
            order_by=(feedback.c.updated.desc(), feedback.c.alert_id),
        )
        .label("rating_rank")
    )
    ranked = (
        select(feedback.c.profile_id, feedback.c.watch_id, feedback.c.article_id, rank)
        .where(
            tuple_(feedback.c.profile_id, feedback.c.watch_id).in_(identities),
            feedback.c.rating == "not_relevant",
        )
        .subquery()
    )
    rows = conn.execute(
        select(
            ranked.c.profile_id,
            ranked.c.watch_id,
            articles.c.title,
            articles.c.description,
        )
        .join(articles, articles.c.id == ranked.c.article_id)
        .where(ranked.c.rating_rank <= 4)
        .order_by(ranked.c.rating_rank)
    )
    result: dict[tuple[str, str], list[dict]] = {}
    for profile, watch, title, excerpt in rows:
        result.setdefault((profile, watch), []).append(
            {"title": title[:220], "excerpt": excerpt[:320]}
        )
    return result


def pending_push(store, conn, ids: list[str], now: float) -> dict:
    if not ready(store, conn):
        return {}
    a, p, d = monitor_alerts.c, push_links.c, monitor_delivery.c
    rank = (
        func.row_number()
        .over(partition_by=p.subscription_id, order_by=(a.created, a.id))
        .label("push_rank")
    )
    ranked = (
        select(p.subscription_id, a.id, a.evidence, rank)
        .select_from(push_links)
        .join(monitor_profiles, monitor_profiles.c.id == p.profile_id)
        .join(monitor_alerts, a.profile_id == p.profile_id)
        .join(
            state,
            (state.c.profile_id == a.profile_id) & (state.c.watch_id == a.watch_id),
        )
        .outerjoin(
            monitor_delivery,
            (d.profile_id == a.profile_id) & (d.watch_id == a.watch_id),
        )
        .where(
            p.subscription_id.in_(ids),
            monitor_profiles.c.expires > now,
            a.created >= p.enabled_at,
            a.created >= now - 86400,
            a.read_at.is_(None),
            d.muted.is_not(True),
            or_(d.snoozed_until.is_(None), d.snoozed_until <= now),
            ~select(push_receipts.c.alert_id)
            .where(push_receipts.c.alert_id == a.id)
            .exists(),
        )
        .subquery()
    )
    return {
        row["subscription_id"]: dict(row)
        for row in conn.execute(
            select(ranked).where(ranked.c.push_rank == 1)
        ).mappings()
    }


def persist(
    store,
    watch,
    marker: tuple[float, str],
    matches: list[dict],
    raw: dict[str, dict],
    event_ids: dict[str, str],
    now: float,
) -> int:
    from app.monitoring import (
        MAX_ALERTS,
        INTERVAL,
        active_profile,
        begin_write,
        controls_available,
        paused,
    )

    profile, ident = watch["profile_id"], watch["id"]
    filters = (state.c.profile_id == profile, state.c.watch_id == ident)
    with store.engine.begin() as conn:
        begin_write(conn)
        if not active_profile(conn, profile, now, lock=True):
            return 0
        current = conn.execute(select(state).where(*filters)).mappings().first()
        if not current or any(
            current[key] != watch[key] for key in ("spec", "cursor_at", "cursor_id")
        ):
            return 0
        if controls_available(conn):
            control = (
                conn.execute(
                    select(monitor_delivery).where(
                        monitor_delivery.c.profile_id == profile,
                        monitor_delivery.c.watch_id == ident,
                    )
                )
                .mappings()
                .first()
            )
            if paused(control, now):
                return 0
        created = 0
        if matches:
            created = insert_alerts(
                store, conn, profile, ident, matches, raw, event_ids, now
            )
        if created:
            obsolete = (
                select(monitor_alerts.c.id)
                .where(monitor_alerts.c.profile_id == profile)
                .order_by(monitor_alerts.c.updated.desc(), monitor_alerts.c.id.desc())
                .offset(MAX_ALERTS)
                .limit(12)
            )
            conn.execute(
                delete(monitor_alerts).where(monitor_alerts.c.id.in_(obsolete))
            )
        conn.execute(
            update(state)
            .where(*filters)
            .values(cursor_at=marker[0], cursor_id=marker[1], status="checked")
        )
        conn.execute(
            update(monitor_watches)
            .where(
                monitor_watches.c.profile_id == profile, monitor_watches.c.id == ident
            )
            .values(checked=now, next_check=now + INTERVAL)
        )
        return created


def insert_alerts(
    store, conn, profile, ident, matches, raw, event_ids, now: float
) -> int:
    observed = event_intelligence.event_items
    filters = (events.c.profile_id == profile,)
    incoming = {event_ids[row["id"]] for row in matches if row["id"] in event_ids}
    canonical = (
        set(
            conn.scalars(
                select(observed.c.event_id)
                .join(events, events.c.article_id == observed.c.article_id)
                .where(*filters, observed.c.event_id.in_(incoming))
            )
        )
        if incoming
        else set()
    )
    previous = [
        dict(row)
        for row in conn.execute(
            select(articles)
            .join(events, events.c.article_id == articles.c.id)
            .where(*filters, events.c.created >= now - 3 * 86400)
            .order_by(events.c.created.desc())
            .limit(100)
        ).mappings()
    ]
    created = 0
    for row in matches:
        article_id = row["id"]
        event_id = event_ids.get(article_id)
        if event_id in canonical or any(
            event_intelligence.event_score(raw[article_id], other) > 0
            for other in previous
        ):
            continue
        event_key = f"event:{event_id}" if event_id else f"story:{article_id}"
        inserted = conn.scalar(
            store.insert(events)
            .values(
                profile_id=profile,
                watch_id=ident,
                event_key=event_key,
                article_id=article_id,
                created=now,
            )
            .on_conflict_do_nothing()
            .returning(events.c.event_key)
        )
        if inserted is None:
            continue
        if event_id:
            canonical.add(event_id)
        previous.append(raw[article_id])
        conn.execute(
            monitor_alerts.insert().values(
                id=secrets.token_hex(16),
                profile_id=profile,
                watch_id=ident,
                created=now,
                updated=now,
                evidence=json.dumps([row], ensure_ascii=False),
            )
        )
        created += 1
    return created


def retry_later(store, watch, now: float):
    from app.monitoring import INTERVAL, active_profile, begin_write

    profile, ident = watch["profile_id"], watch["id"]
    with store.engine.begin() as conn:
        begin_write(conn)
        if active_profile(conn, profile, now, lock=True):
            changed = conn.execute(
                update(state)
                .where(
                    state.c.profile_id == profile,
                    state.c.watch_id == ident,
                    state.c.spec == watch["spec"],
                    state.c.cursor_at == watch["cursor_at"],
                    state.c.cursor_id == watch["cursor_id"],
                )
                .values(status="ai_unavailable")
            ).rowcount
            if changed:
                conn.execute(
                    update(monitor_watches)
                    .where(
                        monitor_watches.c.profile_id == profile,
                        monitor_watches.c.id == ident,
                    )
                    .values(next_check=now + INTERVAL)
                )


def run(
    store, *, now=None, model=None, budget_seconds: float = RUN_SECONDS
) -> RunResult:
    """One bounded archive scan shared by due watches in the existing job."""
    from app.monitoring import controls_available

    now = time.time() if now is None else now
    deadline = time.monotonic() + budget_seconds
    result: RunResult = {
        "watch_agent_status": "checked",
        "watch_agent_checked": 0,
        "watch_agent_alerts": 0,
        "watch_agent_candidates": 0,
        "watch_agent_model_calls": 0,
    }
    until = now - ARRIVAL_SETTLE_SECONDS
    with store.engine.connect() as conn:
        if not ready(store, conn):
            return {**result, "watch_agent_status": "migration_required"}
        due = scope(conn, with_controls=controls_available(conn), now=now)
        if not due:
            return result
        minimum = min((row["cursor_at"], row["cursor_id"]) for row in due)
        if minimum[0] >= until:
            return result
        batch = archive_batch(store, conn, minimum, until)
        negatives = negative_examples(conn, due) if batch else {}

    backlog = len(batch) > PAGE
    raw = {row["id"]: row for row in batch[:PAGE]}
    records = [
        record for row in raw.values() if (record := watch_agent.archive_record(row))
    ]
    grouped = event_intelligence.article_events(store, list(raw))
    tail = batch[PAGE - 1] if backlog else None
    end = (tail["first_seen"], tail["id"]) if tail else (until, "")
    for row in due:
        if (
            time.monotonic() + 0.25 >= deadline
            or result["watch_agent_candidates"]
            > MAX_CANDIDATES_PER_RUN - watch_agent.MAX_CANDIDATES
        ):
            result["watch_agent_status"] = "partial"
            break
        cursor = (row["cursor_at"], row["cursor_id"])
        if cursor >= end:
            continue
        eligible = [
            item
            for item in records
            if (raw[item["id"]]["first_seen"], item["id"]) > cursor
        ]
        watch = watch_agent.Spec.model_validate_json(row["spec"])
        outcome = watch_agent.graph(
            store,
            watch,
            eligible,
            negatives.get((row["profile_id"], row["id"]), []),
            deadline=deadline,
            model=model,
            deliver=lambda matches: persist(
                store,
                row,
                end,
                watch_agent.grouped_matches(matches, raw, grouped),
                raw,
                grouped,
                now,
            ),
        )
        result["watch_agent_candidates"] += len(outcome.get("candidates", ()))
        result["watch_agent_model_calls"] += outcome.get("calls", 0)
        if outcome.get("unavailable"):
            # Preserve the cursor. A future scheduled pass can retry with the same arrivals.
            result["watch_agent_status"] = "ai_unavailable"
            retry_later(store, row, now)
            continue
        result["watch_agent_checked"] += 1
        result["watch_agent_alerts"] += outcome.get("delivered", 0)
    return result
