"""Shared article, quota, verification and delivery state for the web app."""
import base64
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import (
    Boolean, Column, Float, Integer, MetaData, String, Table, Text,
    and_, create_engine, delete, func, or_, select, update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.coverage import topic_expression

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
                                  func.lower(articles.c.description).contains(q, autoescape=True)))
        return stmt

    def page(self, *, hours, source, query, kind, publisher, limit, cursor, topic="all"):
        stmt = self.query(hours, source, query, kind, publisher)
        if topic != "all":
            stmt = stmt.where(topic_expression(articles.c) == topic)
        fingerprint = hashlib.sha256(json.dumps([hours, source, query, kind, publisher, topic]).encode()).hexdigest()[:16]
        with self.engine.connect() as conn:
            total = conn.scalar(select(func.count()).select_from(stmt.subquery()))
            if cursor:
                published, ident = decode_cursor(cursor, fingerprint)
                stmt = stmt.where(or_(articles.c.published_at < published,
                                     and_(articles.c.published_at == published, articles.c.id < ident)))
            rows = [dict(r) for r in conn.execute(stmt.order_by(articles.c.published_at.desc(), articles.c.id.desc()).limit(limit + 1)).mappings()]
        return page_result(rows, total, limit, fingerprint)

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
        for scope, bucket, ceiling in sorted(policies):
            stmt = self.insert(limits).values(scope=scope, bucket=bucket, used=1, touched=time.time())
            admitted = conn.scalar(stmt.on_conflict_do_update(index_elements=[limits.c.scope, limits.c.bucket],
                set_={"used": limits.c.used + 1, "touched": stmt.excluded.touched}, where=limits.c.used < ceiling)
                .returning(limits.c.used))
            if admitted is None:
                raise QuotaReached

    def admit(self, policies):
        try:
            with self.engine.begin() as conn:
                self._admit(conn, policies)
            return True
        except QuotaReached:
            return False

    def claim_refresh(self, *, scheduled=False):
        """Claim one refresh across instances for longer than the function timeout."""
        now = time.time()
        expires = now + 180
        active = and_(limits.c.scope == "feed-refresh-lease", limits.c.bucket == "active")
        with self.engine.begin() as conn:
            claim = self.insert(limits).values(scope="feed-refresh-lease", bucket="active", used=1, touched=expires)
            acquired = conn.scalar(claim.on_conflict_do_update(
                index_elements=[limits.c.scope, limits.c.bucket],
                set_={"touched": claim.excluded.touched}, where=limits.c.touched <= now,
            ).returning(limits.c.touched))
            if acquired is None:
                return None
            if scheduled:
                cooldown = conn.scalar(select(limits.c.touched).where(
                    limits.c.scope == "feed-refresh-lease", limits.c.bucket == "cooldown"))
                if cooldown is not None and cooldown > now:
                    conn.execute(delete(limits).where(active))
                    return None
            return acquired

    def finish_refresh(self, lease, *, cooldown=0):
        with self.engine.begin() as conn:
            released = conn.scalar(delete(limits).where(
                limits.c.scope == "feed-refresh-lease", limits.c.bucket == "active", limits.c.touched == lease,
            ).returning(limits.c.scope))
            if released is not None and cooldown:
                stmt = self.insert(limits).values(scope="feed-refresh-lease", bucket="cooldown", used=1,
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

    def reserve_delivery(self, ident, policies):
        """Atomically reserve recipient quota once for a preview and inbox."""
        try:
            with self.engine.begin() as conn:
                stmt = self.insert(deliveries).values(id=ident, created=time.time())
                if conn.scalar(stmt.on_conflict_do_nothing(index_elements=[deliveries.c.id]).returning(deliveries.c.id)) is not None:
                    self._admit(conn, policies)
                    return "new", None
                row = conn.execute(select(deliveries).where(deliveries.c.id == ident)).one()
                if row.created < time.time() - 3600:
                    return "expired", None
                return "retry", row.provider_id
        except QuotaReached:
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

    def prune(self):
        now = time.time()
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        with self.engine.begin() as conn:
            for table, condition in (
                (codes, codes.c.expires < now), (previews, previews.c.expires < now),
                (limits, limits.c.touched < now - 7 * 86400), (deliveries, deliveries.c.created < now - 30 * 86400),
                (summaries, summaries.c.created < now - 90 * 86400), (articles, articles.c.published_at < cutoff),
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
