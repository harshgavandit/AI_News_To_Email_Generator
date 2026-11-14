"""Shared article, quota, verification and delivery state for the web app."""
import base64
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import (
    Boolean, Column, Float, Index, Integer, MetaData, String, Table, Text,
    and_, bindparam, create_engine, delete, func, or_, select, update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.coverage import REGIONS, topic_expression
from app.sources import BY_ID

schema = MetaData()
articles = Table("brief_articles", schema,
    Column("id", String(40), primary_key=True), Column("url", Text, nullable=False),
    Column("title", Text, nullable=False), Column("description", Text, nullable=False),
    Column("source", String(64), nullable=False), Column("source_id", String(64), nullable=False, index=True),
    Column("publisher", String(140), nullable=False), Column("kind", String(24), nullable=False),
    Column("category", String(100), nullable=False), Column("published_at", String(40), nullable=False, index=True))
sources = Table("brief_sources", schema,
    Column("id", String(64), primary_key=True), Column("enabled", Boolean, nullable=False, default=True),
    Column("available", Boolean, nullable=False, default=False), Column("count", Integer, nullable=False, default=0),
    Column("checked", Float), Column("last_success", Float), Column("error", String(60)))
limits = Table("brief_limits", schema, Column("scope", String(150), primary_key=True),
    Column("bucket", String(30), primary_key=True), Column("used", Integer, nullable=False),
    Column("touched", Float, nullable=False))
codes = Table("brief_codes", schema, Column("id", String(80), primary_key=True),
    Column("mailbox", String(64), nullable=False), Column("proof", String(64), nullable=False),
    Column("expires", Float, nullable=False), Column("tries", Integer, nullable=False))
previews = Table("brief_previews", schema, Column("id", String(80), primary_key=True),
    Column("payload", Text, nullable=False), Column("expires", Float, nullable=False))
deliveries = Table("brief_deliveries", schema, Column("id", String(64), primary_key=True),
    Column("created", Float, nullable=False), Column("provider_id", String(160)))
summaries = Table("brief_summaries", schema, Column("id", String(64), primary_key=True),
    Column("payload", Text, nullable=False), Column("created", Float, nullable=False))
subscriptions = Table("brief_subscriptions", schema,
    Column("mailbox", String(64), primary_key=True),
    Column("email", String(254), nullable=False),
    Column("timezone", String(64), nullable=False),
    Column("next_run", Float, nullable=False, index=True),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("claimed", Float, nullable=False, default=0.0))
mail_batches = Table("brief_mail_batches", schema,
    Column("id", String(64), primary_key=True),
    Column("created", Float, nullable=False), Column("retry_at", Float, nullable=False),
    Column("state", String(24), nullable=False), Column("attempts", Integer, nullable=False),
    Column("size", Integer, nullable=False), Column("message", Text), Column("recipients", Text))
Index("brief_mail_batches_due", mail_batches.c.state, mail_batches.c.retry_at)
mail_suppressions = Table("brief_mail_suppressions", schema, Column("mailbox", String(64), primary_key=True))
mail_events = Table("brief_mail_events", schema, Column("id", String(64), primary_key=True),
    Column("kind", String(32), nullable=False), Column("received_at", Float, nullable=False, index=True))


class QuotaReached(Exception):
    pass


class Store:
    def __init__(self, url):
        if url.startswith(("postgres://", "postgresql://")):
            url = "postgresql+psycopg://" + url.split("://", 1)[1]
        self.engine = create_engine(url, pool_pre_ping=True, **(
            {"connect_args": {"timeout": 20}} if url.startswith("sqlite:") else
            {"pool_size": 2, "max_overflow": 1, "pool_timeout": 5, "connect_args": {"connect_timeout": 5}}
        ))
        self.insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        if self.engine.dialect.name == "sqlite":
            schema.create_all(self.engine)

    def migrate(self):
        schema.create_all(self.engine)

    def source_state(self):
        with self.engine.connect() as conn:
            return {row.id: dict(row._mapping) for row in conn.execute(select(sources))}

    def enable(self, source_id, enabled):
        with self.engine.begin() as conn:
            stmt = self.insert(sources).values(id=source_id, enabled=enabled)
            conn.execute(stmt.on_conflict_do_update(index_elements=[sources.c.id], set_={"enabled": enabled}))

    def ingest(self, source_id, items, available, error=None):
        now = time.time()
        state = {"available": available, "checked": now, "error": error}
        if available:
            state.update(last_success=now, count=len(items))
        with self.engine.begin() as conn:
            if items and available:
                stmt = self.insert(articles)
                values = [{**{k: a[k] for k in ("id", "url", "title", "description", "source", "publisher",
                                                 "category", "published_at")}, "source_id": source_id,
                           "kind": a.get("kind", "news")} for a in items]
                conn.execute(stmt.on_conflict_do_update(index_elements=[articles.c.id],
                    set_={c.name: stmt.excluded[c.name] for c in articles.c if c.name != "id"}), values)
            stmt = self.insert(sources).values(id=source_id, **state)
            conn.execute(stmt.on_conflict_do_update(index_elements=[sources.c.id], set_=state))

    def query(self, hours, source="all", query="", kind="all", publisher="", source_ids=()):
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        stmt = select(articles).outerjoin(sources, articles.c.source_id == sources.c.id).where(
            articles.c.published_at >= cutoff, or_(sources.c.enabled.is_(True), sources.c.enabled.is_(None)))
        if source != "all":
            stmt = stmt.where(or_(articles.c.source == source, articles.c.source_id == source))
        if kind != "all":
            stmt = stmt.where(articles.c.kind == kind)
        if publisher:
            stmt = stmt.where(articles.c.source_id == publisher)
        if source_ids:
            stmt = stmt.where(or_(articles.c.source.in_(source_ids), articles.c.source_id.in_(source_ids)))
        if query:
            q = query.strip().lower()
            stmt = stmt.where(or_(func.lower(articles.c.title).contains(q, autoescape=True),
                                  func.lower(articles.c.description).contains(q, autoescape=True),
                                  func.lower(articles.c.publisher).contains(q, autoescape=True)))
        return stmt

    def page(self, *, hours, source, query, kind, publisher, limit, cursor, topic="all", region=""):
        base = self.query(hours, query=query, kind=kind, publisher=publisher)
        if topic != "all":
            base = base.where(topic_expression(articles.c) == topic)
        if region:
            base = base.where(articles.c.source_id.in_([s.id for s in BY_ID.values() if s.region in REGIONS[region]]))
        stmt = base if source == "all" else base.where(or_(articles.c.source == source, articles.c.source_id == source))
        fingerprint = hashlib.sha256(json.dumps([hours, source, query, kind, publisher, topic, region]).encode()).hexdigest()[:16]
        with self.engine.connect() as conn:
            grouped = base.subquery()
            counts = {group: count for group, count in conn.execute(
                select(grouped.c.source, func.count()).group_by(grouped.c.source))}
            total = sum(counts.values()) if source == "all" else conn.scalar(select(func.count()).select_from(stmt.subquery()))
            if cursor:
                published, ident = decode_cursor(cursor, fingerprint)
                stmt = stmt.where(or_(articles.c.published_at < published,
                                     and_(articles.c.published_at == published, articles.c.id < ident)))
            rows = [dict(r) for r in conn.execute(stmt.order_by(articles.c.published_at.desc(), articles.c.id.desc()).limit(limit + 1)).mappings()]
        return dict(page_result(rows, total, limit, fingerprint), source_counts={**counts, "all": sum(counts.values())})

    def pinned_articles(self, ids):
        if not ids:
            return []
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(self.query(90 * 24).where(articles.c.id.in_(ids))).mappings()]

    def world_candidates(self, hours, source_ids):
        # Cap each topic independently so a burst of posts cannot crowd out the others.
        rank = func.row_number().over(partition_by=topic_expression(articles.c),
            order_by=(articles.c.published_at.desc(), articles.c.id.desc())).label("topic_rank")
        ranked = self.query(hours, source_ids=source_ids).add_columns(rank).subquery()
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(select(ranked).where(ranked.c.topic_rank <= 40)).mappings()]

    def candidates(self, hours, source_ids, terms):
        stmt = self.query(hours, source_ids=source_ids)
        order = (articles.c.published_at.desc(), articles.c.id.desc())
        with self.engine.connect() as conn:
            recent = conn.execute(stmt.order_by(*order).limit(150)).mappings().all()
            if terms:
                # Include older matches; rank the bounded union in Python.
                ranked = conn.execute(stmt.where(or_(*(or_(
                    func.lower(articles.c.title).contains(term, autoescape=True),
                    func.lower(articles.c.description).contains(term, autoescape=True),
                ) for term in sorted(terms)[:16]))).order_by(*order).limit(300)).mappings().all()
                return list({r["id"]: dict(r) for r in [*recent, *ranked]}.values())
            return [dict(r) for r in recent]

    def _admit(self, conn, policies):
        for scope, bucket, ceiling in sorted(policies, key=lambda policy: (policy[0] not in {"digests", "outbound"}, policy)):
            stmt = self.insert(limits).values(scope=scope, bucket=bucket, used=1, touched=time.time())
            admitted = conn.scalar(stmt.on_conflict_do_update(index_elements=[limits.c.scope, limits.c.bucket],
                set_={"used": limits.c.used + 1, "touched": stmt.excluded.touched}, where=limits.c.used < ceiling)
                .returning(limits.c.used))
            if admitted is None:
                raise QuotaReached

    def enqueue_morning_batch(self, ident, now, day, capacity, size, make_message):
        """Advance schedules, reserve quotas, and save the immutable payload together."""
        candidates = select(subscriptions).where(
            subscriptions.c.enabled.is_(True), subscriptions.c.next_run <= now,
            subscriptions.c.claimed <= now,
            ~subscriptions.c.mailbox.in_(select(mail_suppressions.c.mailbox)),
        ).order_by(subscriptions.c.next_run, subscriptions.c.mailbox).limit(size)
        if self.engine.dialect.name == "postgresql":
            candidates = candidates.with_for_update(skip_locked=True)
        recipients, messages = [], []
        with self.engine.begin() as conn:
            rows = conn.execute(candidates).mappings().all()
            pending = [(row["mailbox"], *make_message(row)) for row in rows]
            pending = [item for item in pending if item[1] is not None]
            if not pending:
                return 0
            remaining = size
            for scope, bucket, ceiling in capacity.policies(day, "digests")[::-1]:
                stmt = self.insert(limits).values(scope=scope, bucket=bucket, used=0, touched=now)
                used = conn.scalar(stmt.on_conflict_do_update(
                    index_elements=[limits.c.scope, limits.c.bucket], set_={"touched": now}
                ).returning(limits.c.used))
                remaining = min(remaining, ceiling - used)
            if remaining <= 0:
                return 0
            pending = pending[:remaining]
            scopes = [f"mail:{mailbox}" for mailbox, _, _ in pending]
            stmt = self.insert(limits).values([
                {"scope": scope, "bucket": day, "used": 1, "touched": now} for scope in sorted(scopes)])
            eligible = set(conn.scalars(stmt.on_conflict_do_update(
                index_elements=[limits.c.scope, limits.c.bucket],
                set_={"used": limits.c.used + 1, "touched": now}, where=limits.c.used < 3
            ).returning(limits.c.scope)))
            advance = update(subscriptions).where(subscriptions.c.mailbox == bindparam("recipient_key")).values(
                next_run=bindparam("next_delivery"), claimed=0)
            conn.execute(advance, [{"recipient_key": mailbox, "next_delivery": next_run}
                                   for mailbox, _, next_run in pending])
            for mailbox, message, _ in pending:
                if f"mail:{mailbox}" in eligible:
                    recipients.append(mailbox)
                    messages.append(message)
            if messages:
                conn.execute(update(limits).where(limits.c.scope.in_(["digests", "outbound"]), limits.c.bucket == day)
                             .values(used=limits.c.used + len(messages)))
                conn.execute(mail_batches.insert().values(id=ident, created=now, retry_at=now, state="pending",
                    attempts=0, size=len(messages), message=json.dumps(messages), recipients=json.dumps(recipients)))
        return len(messages)

    def pending_mail_batch(self):
        with self.engine.connect() as conn:
            row = conn.execute(select(mail_batches).where(mail_batches.c.state == "pending")
                               .order_by(mail_batches.c.created, mail_batches.c.id).limit(1)).mappings().first()
            return dict(row) if row else None

    def active_batch_mailboxes(self, mailboxes):
        with self.engine.connect() as conn:
            return set(conn.scalars(select(subscriptions.c.mailbox).where(
                subscriptions.c.mailbox.in_(mailboxes), subscriptions.c.enabled.is_(True),
                ~subscriptions.c.mailbox.in_(select(mail_suppressions.c.mailbox)))))

    def has_due_subscription(self, now):
        with self.engine.connect() as conn:
            return conn.scalar(select(subscriptions.c.mailbox).where(subscriptions.c.enabled.is_(True),
                subscriptions.c.next_run <= now, subscriptions.c.claimed <= now).limit(1)) is not None

    def replace_unattempted_batch(self, ident, messages, mailboxes):
        with self.engine.begin() as conn:
            conn.execute(update(mail_batches).where(mail_batches.c.id == ident, mail_batches.c.attempts == 0)
                         .values(message=json.dumps(messages), recipients=json.dumps(mailboxes), size=len(messages)))

    def update_mail_batch(self, ident, state, attempts, retry_at, *, size=None):
        values = dict(state=state, attempts=attempts, retry_at=retry_at)
        if size is not None:
            values["size"] = size
        if state != "pending":
            values.update(message=None, recipients=None)
        with self.engine.begin() as conn:
            conn.execute(update(mail_batches).where(mail_batches.c.id == ident).values(**values))

    def mail_backlog(self, now):
        with self.engine.connect() as conn:
            due, oldest = conn.execute(select(func.count(), func.min(subscriptions.c.next_run)).where(
                subscriptions.c.enabled.is_(True), subscriptions.c.next_run <= now)).one()
            totals = dict((state, size) for state, size in conn.execute(
                select(mail_batches.c.state, func.sum(mail_batches.c.size)).group_by(mail_batches.c.state)
                .where(mail_batches.c.created >= now - 86400)))
            outcomes = dict((kind, count) for kind, count in conn.execute(select(mail_events.c.kind, func.count())
                .where(mail_events.c.received_at >= now - 86400).group_by(mail_events.c.kind)))
            queued, first_queued = conn.execute(select(func.sum(mail_batches.c.size), func.min(mail_batches.c.created))
                .where(mail_batches.c.state == "pending")).one()
            return {"due": due, "oldest_due_seconds": max(0, round(now - oldest)) if oldest else 0,
                    "queued": queued or 0, "oldest_queued_seconds": max(0, round(now - first_queued)) if first_queued else 0,
                    "batches_24h": totals, "provider_events_24h": outcomes}

    def admit(self, policies):
        try:
            with self.engine.begin() as conn:
                self._admit(conn, policies)
            return True
        except QuotaReached:
            return False

    def _admit_windows(self, conn, policies):
        now = time.time()
        for scope, window, maximum in sorted(policies):
            scope = f"sliding:{scope}"
            # An upsert serializes requests for this scope before counting recent events.
            lock = self.insert(limits).values(scope=scope, bucket="lock", used=0, touched=now)
            conn.execute(lock.on_conflict_do_update(
                index_elements=[limits.c.scope, limits.c.bucket], set_={"touched": now}))
            events = and_(limits.c.scope == scope, limits.c.bucket != "lock")
            conn.execute(delete(limits).where(events, limits.c.touched <= now - window))
            count, first = conn.execute(select(func.count(), func.min(limits.c.touched)).where(events)).one()
            if count >= maximum:
                raise QuotaReached(max(1, int(first + window - now) + 1))
            conn.execute(limits.insert().values(scope=scope, bucket=os.urandom(12).hex(), used=1, touched=now))

    def admit_windows(self, policies):
        try:
            with self.engine.begin() as conn:
                self._admit_windows(conn, policies)
        except QuotaReached as exc:
            return exc.args[0]
        return None

    def claim_refresh(self, *, scheduled=False, scope="feed-refresh-lease"):
        """Claim one refresh across instances for longer than the function timeout."""
        now = time.time()
        expires = now + 180
        active = and_(limits.c.scope == scope, limits.c.bucket == "active")
        with self.engine.begin() as conn:
            claim = self.insert(limits).values(scope=scope, bucket="active", used=1, touched=expires)
            acquired = conn.scalar(claim.on_conflict_do_update(
                index_elements=[limits.c.scope, limits.c.bucket],
                set_={"touched": claim.excluded.touched}, where=limits.c.touched <= now,
            ).returning(limits.c.touched))
            if acquired is None:
                return None
            if scheduled:
                cooldown = conn.scalar(select(limits.c.touched).where(
                    limits.c.scope == scope, limits.c.bucket == "cooldown"))
                if cooldown is not None and cooldown > now:
                    conn.execute(delete(limits).where(active))
                    return None
            return acquired

    def finish_refresh(self, lease, *, cooldown=0, scope="feed-refresh-lease"):
        with self.engine.begin() as conn:
            released = conn.scalar(delete(limits).where(
                limits.c.scope == scope, limits.c.bucket == "active", limits.c.touched == lease,
            ).returning(limits.c.scope))
            if released is not None and cooldown:
                stmt = self.insert(limits).values(scope=scope, bucket="cooldown", used=1,
                                                  touched=time.time() + cooldown)
                conn.execute(stmt.on_conflict_do_update(index_elements=[limits.c.scope, limits.c.bucket],
                                                       set_={"touched": stmt.excluded.touched}))

    def save_code(self, ident, mailbox, proof, expires):
        with self.engine.begin() as conn:
            conn.execute(codes.insert().values(id=ident, mailbox=mailbox, proof=proof, expires=expires, tries=0))

    def consume_code(self, ident, mailbox, proof):
        eligible = and_(codes.c.id == ident, codes.c.mailbox == mailbox, codes.c.expires > time.time(), codes.c.tries < 5)
        with self.engine.begin() as conn:
            if conn.scalar(delete(codes).where(eligible, codes.c.proof == proof).returning(codes.c.id)) is not None:
                return True
            conn.execute(update(codes).where(eligible).values(tries=codes.c.tries + 1))
        return False

    def save_preview(self, ident, payload, expires):
        with self.engine.begin() as conn:
            conn.execute(previews.insert().values(id=ident, payload=json.dumps(payload), expires=expires))

    def get_preview(self, ident):
        with self.engine.connect() as conn:
            payload = conn.scalar(select(previews.c.payload).where(previews.c.id == ident, previews.c.expires > time.time()))
        return json.loads(payload) if payload else None

    def reserve_delivery(self, ident, policies, *, windows=()):
        """Atomically reserve recipient quota once for a preview and inbox."""
        try:
            with self.engine.begin() as conn:
                stmt = self.insert(deliveries).values(id=ident, created=time.time())
                if conn.scalar(stmt.on_conflict_do_nothing(index_elements=[deliveries.c.id]).returning(deliveries.c.id)) is not None:
                    self._admit_windows(conn, windows)
                    self._admit(conn, policies)
                    return "new", None
                row = conn.execute(select(deliveries).where(deliveries.c.id == ident)).one()
                if row.created < time.time() - 3600:
                    return "expired", None
                return "retry", row.provider_id
        except QuotaReached as exc:
            if exc.args:
                return "limited", exc.args[0]
            return "limited", None

    def record_delivery(self, ident, provider_id):
        with self.engine.begin() as conn:
            conn.execute(update(deliveries).where(deliveries.c.id == ident).values(provider_id=provider_id))

    def get_summary(self, ident):
        with self.engine.connect() as conn:
            payload = conn.scalar(select(summaries.c.payload).where(summaries.c.id == ident))
        return json.loads(payload) if payload else None

    def save_summary(self, ident, payload):
        with self.engine.begin() as conn:
            stmt = self.insert(summaries).values(id=ident, payload=json.dumps(payload), created=time.time())
            conn.execute(stmt.on_conflict_do_nothing(index_elements=[summaries.c.id]))

    def subscription(self, mailbox):
        with self.engine.connect() as conn:
            row = conn.execute(select(subscriptions).where(subscriptions.c.mailbox == mailbox)).first()
            return dict(row._mapping) if row else None

    def subscribe(self, mailbox, email, timezone, next_run):
        with self.engine.begin() as conn:
            stmt = self.insert(subscriptions).values(
                mailbox=mailbox, email=email, timezone=timezone, next_run=next_run, enabled=True, claimed=0.0
            )
            conn.execute(stmt.on_conflict_do_update(
                index_elements=[subscriptions.c.mailbox],
                set_={
                    "email": email,
                    "timezone": timezone,
                    "next_run": next_run,
                    "enabled": True,
                    "claimed": subscriptions.c.claimed,
                }
            ))

    def unsubscribe(self, mailbox):
        with self.engine.begin() as conn:
            conn.execute(update(subscriptions).where(subscriptions.c.mailbox == mailbox).values(enabled=False))

    def due_subscriptions(self, now):
        with self.engine.connect() as conn:
            stmt = select(subscriptions).where(
                subscriptions.c.enabled.is_(True),
                subscriptions.c.next_run <= now,
                subscriptions.c.claimed <= now,
            )
            return [dict(row._mapping) for row in conn.execute(stmt.order_by(subscriptions.c.next_run).limit(3))]

    def suppressed(self, mailbox):
        with self.engine.connect() as conn:
            return conn.scalar(select(mail_suppressions.c.mailbox).where(mail_suppressions.c.mailbox == mailbox)) is not None

    def record_mail_event(self, ident, kind, mailboxes):
        with self.engine.begin() as conn:
            stmt = self.insert(mail_events).values(id=ident, kind=kind, received_at=time.time())
            inserted = conn.scalar(stmt.on_conflict_do_nothing().returning(mail_events.c.id))
            if not inserted or not mailboxes:
                return
            conn.execute(self.insert(mail_suppressions).values([{"mailbox": value} for value in sorted(mailboxes)])
                         .on_conflict_do_nothing())
            conn.execute(update(subscriptions).where(subscriptions.c.mailbox.in_(mailboxes)).values(enabled=False))

    def claim_subscription(self, mailbox, now, lease_time=180):
        with self.engine.begin() as conn:
            stmt = update(subscriptions).where(
                subscriptions.c.mailbox == mailbox,
                subscriptions.c.enabled.is_(True),
                subscriptions.c.next_run <= now,
                subscriptions.c.claimed <= now,
            ).values(claimed=now + lease_time)
            result = conn.execute(stmt)
            return result.rowcount > 0

    def reschedule_subscription(self, mailbox, next_run):
        with self.engine.begin() as conn:
            conn.execute(update(subscriptions).where(subscriptions.c.mailbox == mailbox).values(
                next_run=next_run, claimed=0.0
            ))

    def prune(self):
        now = time.time()
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        with self.engine.begin() as conn:
            for table, condition in (
                (codes, codes.c.expires < now), (previews, previews.c.expires < now),
                (limits, limits.c.touched < now - 7 * 86400), (deliveries, deliveries.c.created < now - 30 * 86400),
                (summaries, summaries.c.created < now - 90 * 86400), (articles, articles.c.published_at < cutoff),
                (mail_batches, mail_batches.c.created < now - 7 * 86400),
                (mail_events, mail_events.c.received_at < now - 30 * 86400),
            ):
                conn.execute(delete(table).where(condition))


def decode_cursor(cursor, fingerprint):
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor).decode())
        if (not isinstance(value, list) or len(value) != 3 or value[2] != fingerprint or
                not all(isinstance(v, str) for v in value)):
            raise ValueError
        datetime.fromisoformat(value[0])
        return value[:2]
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Invalid page cursor") from exc


def page_result(rows, total, limit, fingerprint):
    shown = rows[:limit]
    cursor = None
    if len(rows) > limit:
        last = shown[-1]
        cursor = base64.urlsafe_b64encode(json.dumps([last["published_at"], last["id"], fingerprint]).encode()).decode()
    return {"articles": shown, "total": total, "next_cursor": cursor}


@lru_cache(maxsize=2)
def connect(url):
    return Store(url)


def get_store():
    url = os.getenv("NEWS_DATABASE_URL")
    return connect(url) if url else None
