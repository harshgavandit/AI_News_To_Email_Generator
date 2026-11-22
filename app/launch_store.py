"""Shared article, quota, verification and delivery state for the web app."""
import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import urlsplit

from sqlalchemy import (
    Boolean, Column, Float, Index, Integer, LargeBinary, MetaData, String, Table, Text,
    and_, bindparam, case, create_engine, delete, func, inspect, literal, literal_column, or_, select, tuple_, update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError

from app.coverage import topic_for
from app.discovery import catalog_filters, facet_counts, page_fingerprint, page_result, page_window, search_terms, search_text
from app.sources import BY_ID
from app.article_language import article_language, is_not_foreign_article
from app.article_metadata import author_identity, metadata_for, restore_metadata
from app.community import GENERAL_DEV_FEEDS, dev_article_in_scope
from app.news_signals import MATERIAL_TERMS

schema = MetaData()
articles = Table("brief_articles", schema,
    Column("id", String(40), primary_key=True), Column("url", Text, nullable=False),
    Column("title", Text, nullable=False), Column("description", Text, nullable=False),
    Column("source", String(64), nullable=False), Column("source_id", String(64), nullable=False, index=True),
    Column("publisher", String(140), nullable=False), Column("kind", String(24), nullable=False),
    Column("category", String(100), nullable=False), Column("published_at", String(40), nullable=False, index=True),
    Column("topic", String(32)), Column("search_title", Text), Column("search_description", Text),
    Column("search_publisher", Text), Column("metadata_json", Text), Column("subject_keys", Text),
    Column("community_relevant", Boolean), Column("source_eligible", Boolean), Column("author_key", String(39)),
    Column("classification_version", Integer))
discovery_columns = (articles.c.topic, articles.c.search_title, articles.c.search_description, articles.c.search_publisher,
                     articles.c.metadata_json, articles.c.subject_keys, articles.c.community_relevant,
                     articles.c.source_eligible, articles.c.author_key, articles.c.classification_version)
research_vectors = Table("brief_research_vectors", schema,
    Column("id", String(40), primary_key=True), Column("encoder", String(100), nullable=False),
    Column("title", Text, nullable=False), Column("description", Text, nullable=False),
    Column("embedding", LargeBinary, nullable=False))
monitor_profiles = Table("brief_monitor_profiles", schema,
    Column("id", String(64), primary_key=True), Column("expires", Float, nullable=False, index=True),
    Column("revision", Integer, nullable=False))
monitor_watches = Table("brief_monitor_watches", schema,
    Column("profile_id", String(64), primary_key=True), Column("id", String(40), primary_key=True),
    Column("query", String(150), nullable=False), Column("topic", String(24), nullable=False),
    Column("created", Float, nullable=False), Column("next_check", Float, nullable=False, index=True),
    Column("checked", Float))
monitor_alerts = Table("brief_monitor_alerts", schema,
    Column("id", String(32), primary_key=True), Column("profile_id", String(64), nullable=False),
    Column("watch_id", String(40), nullable=False), Column("created", Float, nullable=False, index=True),
    Column("updated", Float, nullable=False), Column("read_at", Float), Column("evidence", Text, nullable=False))
Index("brief_monitor_alerts_inbox", monitor_alerts.c.profile_id, monitor_alerts.c.updated)
monitor_delivery = Table("brief_monitor_delivery", schema,
    Column("profile_id", String(64), primary_key=True), Column("watch_id", String(40), primary_key=True),
    Column("muted", Boolean, nullable=False), Column("snoozed_until", Float))
source_order = tuple(BY_ID)
article_indexes = (
    Index("brief_articles_page", articles.c.published_at, articles.c.id),
    Index("brief_articles_source_page", articles.c.source_id, articles.c.published_at, articles.c.id),
    Index("brief_articles_topic_page", articles.c.topic, articles.c.published_at, articles.c.id),
)
search_document = (func.coalesce(articles.c.search_title, literal_column("''")) + literal_column("' '")
                   + func.coalesce(articles.c.search_description, literal_column("''")) + literal_column("' '")
                   + func.coalesce(articles.c.search_publisher, literal_column("''")))


def search_rank(query):
    title, publisher, excerpt = articles.c.search_title, articles.c.search_publisher, articles.c.search_description
    score = case((title.contains(query, autoescape=True), 10), else_=0)
    score += case((excerpt.contains(query, autoescape=True), 3), else_=0)
    for term in search_terms(query) or (query,):
        score += case((title.contains(term, autoescape=True), 3), else_=0)
        score += case((publisher.contains(term, autoescape=True), 1), else_=0)
        score += case((excerpt.contains(term, autoescape=True), 1), else_=0)
    return score


sources = Table("brief_sources", schema,
    Column("id", String(64), primary_key=True), Column("enabled", Boolean, nullable=False, default=True),
    Column("available", Boolean, nullable=False, default=False), Column("count", Integer, nullable=False, default=0),
    Column("checked", Float), Column("last_success", Float), Column("error", String(60)))
feed_validators = Table("brief_feed_validators", schema,
    Column("id", String(64), primary_key=True), Column("feed_url", Text, nullable=False),
    Column("resource_url", Text, nullable=False), Column("etag", String(512)), Column("last_modified", String(80)),
    Column("expires", Float, nullable=False))
feed_retries = Table("brief_feed_retries", schema,
    Column("id", String(64), primary_key=True), Column("failures", Integer, nullable=False),
    Column("retry_at", Float, nullable=False))
article_feeds = Table("brief_article_feeds", schema,
    Column("article_id", String(40), primary_key=True), Column("source_id", String(64), primary_key=True))
feed_diagnostics = Table("brief_feed_diagnostics", schema,
    Column("id", String(64), primary_key=True), Column("observed", Integer, nullable=False),
    Column("rejected", Integer, nullable=False), Column("updated", Float, nullable=False))
feed_checks = Table("brief_feed_checks", schema,
    Column("source_id", String(64), primary_key=True), Column("checked", Float, primary_key=True),
    Column("available", Boolean, nullable=False), Column("count", Integer, nullable=False),
    Column("unchanged", Boolean, nullable=False), Column("duration_ms", Integer), Column("error", String(60)))
Index("brief_feed_checks_time", feed_checks.c.checked)
limits = Table("brief_limits", schema, Column("scope", String(150), primary_key=True),
    Column("bucket", String(30), primary_key=True), Column("used", Integer, nullable=False),
    Column("touched", Float, nullable=False))
codes = Table("brief_codes", schema, Column("id", String(80), primary_key=True),
    Column("mailbox", String(64), nullable=False), Column("proof", String(64), nullable=False),
    Column("expires", Float, nullable=False), Column("tries", Integer, nullable=False))
mail_session_revocations = Table("brief_mail_session_revocations", schema,
    Column("digest", String(64), primary_key=True), Column("expires", Float, nullable=False, index=True))
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
mail_curiosity = Table("brief_mail_curiosity", schema,
    Column("mailbox", String(64), primary_key=True), Column("payload", Text, nullable=False),
    Column("updated", Float, nullable=False))
# Fresh Curiosity Cards worth keeping after their articles leave the 90-day archive.
curiosity_library = Table("brief_curiosity_library", schema,
    Column("id", String(64), primary_key=True), Column("payload", Text, nullable=False),
    Column("score", Integer, nullable=False), Column("saved", Float, nullable=False))
mail_batches = Table("brief_mail_batches", schema,
    Column("id", String(64), primary_key=True),
    Column("created", Float, nullable=False), Column("retry_at", Float, nullable=False),
    Column("state", String(24), nullable=False), Column("attempts", Integer, nullable=False),
    Column("size", Integer, nullable=False), Column("message", Text), Column("recipients", Text))
Index("brief_mail_batches_due", mail_batches.c.state, mail_batches.c.retry_at)
mail_suppressions = Table("brief_mail_suppressions", schema, Column("mailbox", String(64), primary_key=True))
mail_events = Table("brief_mail_events", schema, Column("id", String(64), primary_key=True),
    Column("kind", String(32), nullable=False), Column("received_at", Float, nullable=False, index=True))
mail_outcomes = Table("brief_mail_outcomes", schema,
    Column("id", String(64), primary_key=True), Column("provider_id", String(160), nullable=False, index=True),
    Column("kind", String(32), nullable=False), Column("occurred_at", Float, nullable=False),
    Column("received_at", Float, nullable=False))
contributions = Table("brief_contributions", schema,
    Column("id", String(40), primary_key=True), Column("mailbox", String(64), nullable=False, index=True),
    Column("email", String(254), nullable=False), Column("article_id", String(40), nullable=False, index=True),
    Column("article_url", Text, nullable=False), Column("author_name", String(140), nullable=False),
    Column("body_markdown", Text, nullable=False), Column("permission_evidence", Text, nullable=False),
    Column("terms_version", String(40), nullable=False), Column("state", String(24), nullable=False, index=True),
    Column("created", Float, nullable=False), Column("updated", Float, nullable=False), Column("review_note", Text),
    Column("events", Text, nullable=False))
Index("brief_contributions_review", contributions.c.state, contributions.c.created, contributions.c.id)
reading_permissions = Table("brief_reading_permissions", schema,
    Column("article_id", String(40), primary_key=True), Column("submission_id", String(40), nullable=False),
    Column("author_name", String(140), nullable=False), Column("body_markdown", Text, nullable=False),
    Column("body_html", Text, nullable=False), Column("article_url", Text, nullable=False),
    Column("active", Boolean, nullable=False), Column("approved_at", Float, nullable=False))


class QuotaReached(Exception):
    pass


CLASSIFICATION_VERSION = 4


def discovery_fields(article):
    from app.intelligence import subjects_for
    from app.news import article_in_scope
    metadata = metadata_for(article)
    source = BY_ID.get(article["source_id"])
    path = urlsplit(article.get("url", "")).path
    eligible = not source or article_in_scope(source, path, article["title"], metadata.get("tags", []))
    publisher = " ".join([article["publisher"], metadata.get("author", ""), *metadata.get("tags", []),
                          *metadata.get("technical_terms", [])])
    return {"topic": topic_for(article), "search_title": search_text(article["title"]),
            "search_description": search_text(article["description"]), "search_publisher": search_text(publisher),
            "subject_keys": "|" + "|".join(subjects_for(article)) + "|",
            "source_eligible": eligible, "author_key": author_identity(article), "classification_version": CLASSIFICATION_VERSION,
            "community_relevant": (dev_article_in_scope(article) if article["source_id"] in GENERAL_DEV_FEEDS else None)}


def backfill_discovery(conn):
    stmt = select(*(articles.c[key] for key in ("id", "url", "source_id", "source", "title", "description", "publisher",
                                               "category", "kind", "metadata_json"))).where(or_(
        articles.c.topic.is_(None), articles.c.subject_keys.is_(None), articles.c.source_eligible.is_(None),
        articles.c.author_key.is_(None),
        articles.c.classification_version.is_(None), articles.c.classification_version != CLASSIFICATION_VERSION,
        and_(articles.c.source_id.in_(GENERAL_DEV_FEEDS), articles.c.community_relevant.is_(None))))
    patch = update(articles).where(articles.c.id == bindparam("article_id"))
    while rows := conn.execute(stmt.order_by(articles.c.id).limit(500)).mappings().all():
        conn.execute(patch, [{"article_id": row["id"], **discovery_fields(restore_metadata(row))} for row in rows])


def install_search_index(conn):
    """Index the same normalized substring predicate used by regular search."""
    try:
        with conn.begin_nested():
            conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            namespace = conn.exec_driver_sql("""
                SELECT n.nspname FROM pg_extension AS e
                JOIN pg_namespace AS n ON n.oid = e.extnamespace WHERE e.extname = 'pg_trgm'
            """).scalar_one()
            operator_schema = conn.dialect.identifier_preparer.quote_identifier(namespace)
            expression = search_document.compile(dialect=conn.dialect, compile_kwargs={"include_table": False})
            conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS brief_articles_search_trgm ON brief_articles "
                                 f"USING gin (({expression}) {operator_schema}.gin_trgm_ops)")
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) not in {"42501", "0A000", "58P01", "55P03"}:
            raise
        return "unavailable"
    return "trigram"


class Store:
    def __init__(self, url):
        # Register additive intelligence tables before creating a local archive.
        from app import event_intelligence, radar_store, research_projects, watch_rules  # noqa: F401
        if url.startswith(("postgres://", "postgresql://")):
            url = "postgresql+psycopg://" + url.split("://", 1)[1]
        self.engine = create_engine(url, pool_pre_ping=True, **(
            {"connect_args": {"timeout": 20}} if url.startswith("sqlite:") else
            {"pool_size": 2, "max_overflow": 1, "pool_timeout": 5, "connect_args": {"connect_timeout": 5}}
        ))
        self.insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        self._discovery_ready = False
        self._syndication_ready = False
        self._feed_state_ready = False
        self._mail_revocations_ready = False
        self._curiosity_schema_ready = False
        self._schema_lock = threading.Lock()
        self._source_stats_lock = threading.Lock()
        self._source_stats = {}
        self._source_stats_until = 0.0
        if self.engine.dialect.name == "sqlite":
            schema.create_all(self.engine)
            self.ensure_discovery_schema()
            self._event_tables_ready = True
            self._radar_tables_ready = True
            self._curiosity_schema_ready = True

    def ensure_discovery_schema(self):
        # Existing deployments can upgrade in place. Old code can still write during rollout.
        if self._discovery_ready:
            return
        with self._schema_lock, self.engine.begin() as conn:
            if self._discovery_ready:
                return
            known = {column["name"] for column in inspect(conn).get_columns(articles.name)}
            missing = [column for column in discovery_columns if column.name not in known]
            if missing:
                if self.engine.dialect.name == "postgresql":
                    conn.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                    conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
                else:
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                known = {column["name"] for column in inspect(conn).get_columns(articles.name)}
                for column in missing:
                    if column.name not in known:
                        conn.exec_driver_sql(f"ALTER TABLE brief_articles ADD COLUMN {column.name} {column.type.compile(conn.dialect)}")
                backfill_discovery(conn)
                article_indexes[-1].create(conn, checkfirst=True)
        self._discovery_ready = True

    def migrate(self):
        schema.create_all(self.engine)
        self.ensure_discovery_schema()
        self._event_tables_ready = True
        self._radar_tables_ready = True
        with self.engine.begin() as conn:
            for index in article_indexes:
                index.create(conn, checkfirst=True)
            backfill_discovery(conn)
        if self.engine.dialect.name == "postgresql":
            with self.engine.begin() as conn:
                from app import vector_search
                self._semantic_index_ready = vector_search.install(conn)
                return install_search_index(conn)
        return "portable"

    def source_archive_stats(self):
        # Reuse the retained-article count across search requests. Availability
        # and last check times are read separately on every request.
        with self._source_stats_lock:
            if time.monotonic() >= self._source_stats_until:
                stmt = select(articles.c.source_id,
                              func.max(articles.c.published_at).label("latest_published_at"),
                              func.count().label("retained_count")).group_by(articles.c.source_id)
                with self.engine.connect() as conn:
                    self._source_stats = {row.source_id: {"latest_published_at": row.latest_published_at,
                        "retained_count": row.retained_count} for row in conn.execute(stmt)}
                self._source_stats_until = time.monotonic() + 60
            return self._source_stats

    def source_state(self, *, include_archive=True):
        self.ensure_feed_state_schema()
        latest = self.source_archive_stats() if include_archive else {}
        stmt = select(sources, feed_retries.c.retry_at).outerjoin(feed_retries, feed_retries.c.id == sources.c.id)
        with self.engine.connect() as conn:
            return {row.id: {**dict(row._mapping), **latest.get(row.id, {})} for row in conn.execute(stmt)}

    def ensure_syndication_schema(self):
        if self._syndication_ready:
            return
        with self._schema_lock, self.engine.begin() as conn:
            if self._syndication_ready:
                return
            if self.engine.dialect.name == "postgresql":
                conn.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
            contributions.create(conn, checkfirst=True)
            reading_permissions.create(conn, checkfirst=True)
        self._syndication_ready = True

    def ensure_feed_state_schema(self):
        if not self._feed_state_ready:
            with self._schema_lock, self.engine.begin() as conn:
                tables = (feed_validators, feed_retries, article_feeds, feed_diagnostics, feed_checks)
                inspector = inspect(conn)
                if not all(inspector.has_table(table.name) for table in tables):
                    if conn.dialect.name == "postgresql":
                        conn.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                        conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
                    else:
                        conn.exec_driver_sql("BEGIN IMMEDIATE")
                    for table in tables:
                        table.create(conn, checkfirst=True)
            self._feed_state_ready = True

    def current_feed_validators(self):
        self.ensure_feed_state_schema()
        with self.engine.connect() as conn:
            rows = conn.execute(select(feed_validators).where(feed_validators.c.expires > time.time())).mappings()
            return {row["id"]: dict(row) for row in rows}

    def with_reading_access(self, rows, *, include_body=False):
        from app.syndication import annotate_reading
        return annotate_reading(self, rows, include_body=include_body)

    def enable(self, source_id, enabled):
        with self.engine.begin() as conn:
            stmt = self.insert(sources).values(id=source_id, enabled=enabled)
            conn.execute(stmt.on_conflict_do_update(index_elements=[sources.c.id], set_={"enabled": enabled}))

    def ingest(self, source_id, items, available, error=None, *, feed_url=None, validators=None,
               unchanged=False, retry_after=0, diagnostics=None, duration_ms=None):
        self.ensure_feed_state_schema()
        if items and available:
            self.ensure_discovery_schema()
            items = [{**article, "detected_language": article_language(article)} for article in items]
            source = BY_ID.get(source_id)
            if source and source.require_english:
                eligible = [article for article in items if is_not_foreign_article(article)]
                if diagnostics:
                    diagnostics = {**diagnostics, "rejected": diagnostics["rejected"] + len(items) - len(eligible)}
                items = eligible
        now = time.time()
        state = {"available": available, "checked": now, "error": error}
        if available and not unchanged:
            state.update(last_success=now, count=len(items))
        with self.engine.begin() as conn:
            conn.execute(self.insert(feed_checks).values(source_id=source_id, checked=now, available=available,
                count=len(items), unchanged=unchanged, duration_ms=duration_ms, error=error).on_conflict_do_nothing())
            if diagnostics and available:
                stmt = self.insert(feed_diagnostics).values(id=source_id, updated=now, **diagnostics)
                conn.execute(stmt.on_conflict_do_update(index_elements=[feed_diagnostics.c.id],
                    set_={"updated": now, **diagnostics}))
            if unchanged:
                conn.execute(update(sources).where(sources.c.id == source_id, sources.c.last_success.is_not(None))
                             .values(**state, last_success=now))
                conn.execute(delete(feed_retries).where(feed_retries.c.id == source_id))
                conn.execute(update(feed_validators).where(feed_validators.c.id == source_id,
                    feed_validators.c.feed_url == feed_url).values(expires=now + 7 * 86400))
                return
            if items and available:
                stmt = self.insert(articles)
                values = [{**{k: a[k] for k in ("id", "url", "title", "description", "source", "publisher",
                                                 "category", "published_at")}, "source_id": source_id,
                           "kind": a.get("kind", "news"),
                           "metadata_json": json.dumps(metadata_for(a), ensure_ascii=False)} for a in items]
                values.sort(key=lambda row: row["id"])
                ids = [row["id"] for row in values]
                for article in values:
                    article.update(discovery_fields(restore_metadata(article)))
                # Registry order owns overlapping publisher feeds regardless of refresh completion order.
                fields = [c for c in articles.c if c.name != "id"]
                changed = or_(*(c.is_distinct_from(stmt.excluded[c.name]) for c in fields))
                preferred = source_order[:source_order.index(source_id)] if source_id in BY_ID else source_order
                if preferred:
                    paused = select(sources.c.id).where(sources.c.id == articles.c.source_id,
                                                        sources.c.enabled.is_(False)).exists()
                    changed &= or_(articles.c.source_id.not_in([literal(ident) for ident in preferred]), paused)
                # Preserve the original feed of an archived row before a preferred feed can replace it.
                sightings = select(articles.c.id, articles.c.source_id).where(articles.c.id.in_(ids))
                conn.execute(self.insert(article_feeds).from_select(["article_id", "source_id"], sightings)
                             .on_conflict_do_nothing())
                conn.execute(stmt.on_conflict_do_update(index_elements=[articles.c.id],
                    set_={c.name: stmt.excluded[c.name] for c in fields},
                    where=changed), values)
                conn.execute(self.insert(article_feeds).on_conflict_do_nothing(),
                             [{"article_id": ident, "source_id": source_id} for ident in ids])
            stmt = self.insert(sources).values(id=source_id, **state)
            conn.execute(stmt.on_conflict_do_update(index_elements=[sources.c.id], set_=state))
            if available:
                conn.execute(delete(feed_retries).where(feed_retries.c.id == source_id))
            if not available or retry_after or error == "rate_limited":
                previous = conn.scalar(select(feed_retries.c.failures).where(feed_retries.c.id == source_id)) or 0
                # The source upsert above serializes writes for this feed, including a recovery.
                failures = min(previous + 1, 5)
                delay = max(retry_after, (0, 300, 900, 1800, 3600)[failures - 1],
                            900 if error == "rate_limited" else 0)
                retry = {"failures": failures, "retry_at": now + delay}
                attempt = self.insert(feed_retries).values(id=source_id, **retry)
                conn.execute(attempt.on_conflict_do_update(index_elements=[feed_retries.c.id], set_=retry))
            if available and feed_url:
                if validators:
                    data = {**validators, "feed_url": feed_url, "expires": now + 7 * 86400}
                    stmt = self.insert(feed_validators).values(id=source_id, **data)
                    conn.execute(stmt.on_conflict_do_update(index_elements=[feed_validators.c.id], set_=data))
                else:
                    conn.execute(delete(feed_validators).where(feed_validators.c.id == source_id))

    def query(self, hours, source="all", query="", kind="all", publisher="", source_ids=(), now=None,
              topic="all", region="", coverage="", language="", subject=""):
        self.ensure_discovery_schema()
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(hours=hours)).isoformat()
        stmt = select(articles).outerjoin(sources, articles.c.source_id == sources.c.id).where(
            articles.c.published_at.between(cutoff, now.isoformat()),
            articles.c.community_relevant.is_not(False),
            articles.c.source_eligible.is_not(False),
            or_(sources.c.enabled.is_(True), sources.c.enabled.is_(None)))
        if source != "all":
            stmt = stmt.where(or_(articles.c.source == source, articles.c.source_id == source))
        if kind != "all":
            stmt = stmt.where(articles.c.kind == kind)
        if publisher:
            stmt = stmt.where(articles.c.source_id == publisher)
        if source_ids:
            stmt = stmt.where(or_(articles.c.source.in_(source_ids), articles.c.source_id.in_(source_ids)))
        if region or coverage or language:
            stmt = stmt.where(articles.c.source_id.in_(catalog_filters(region, coverage, language)))
        if topic != "all":
            stmt = stmt.where(articles.c.topic == topic)
        if subject:
            stmt = stmt.where(articles.c.subject_keys.contains(f"|{subject}|", autoescape=True))
        if query:
            terms = search_terms(query) or (query,)
            stmt = stmt.where(*(search_document.contains(term, autoescape=True) for term in terms))
        return stmt

    def page(self, *, hours, source, query, kind, publisher, limit, cursor, topic="all", region="", sort="latest",
             coverage="", language="", subject=""):
        fingerprint = page_fingerprint(hours, source, query, kind, publisher, topic, region, sort, coverage, language, subject)
        ranked = sort == "relevance" and bool(query)
        anchor, marker = page_window(cursor, fingerprint, ranked=ranked)
        base = self.query(hours, query=query, kind=kind, publisher=publisher, coverage=coverage, now=anchor, subject=subject)
        stmt = self.query(hours, source, query, kind, publisher, now=anchor, topic=topic, region=region,
                          coverage=coverage, language=language, subject=subject)
        columns = (articles.c.published_at, articles.c.id)
        if ranked:
            score = search_rank(query)
            stmt = stmt.add_columns(score.label("search_score"))
            columns = (score, *columns)
        with self.engine.connect() as conn:
            key = (articles.c.source_id, articles.c.source, articles.c.topic)
            groups = conn.execute(base.with_only_columns(*key, func.count()).group_by(*key)).all()
            counts = facet_counts(groups, source=source, topic=topic, region=region, language=language)
            if marker:
                after = tuple_(*marker)
                stmt = stmt.where(tuple_(*columns) > after if sort == "oldest" else tuple_(*columns) < after)
            order = [column.asc() if sort == "oldest" else column.desc() for column in columns]
            rows = [dict(r) for r in conn.execute(stmt.order_by(*order).limit(limit + 1)).mappings()]
        return {**page_result(self.with_reading_access(rows), counts["total"], limit, fingerprint, anchor), **counts}

    def pinned_articles(self, ids):
        if not ids:
            return []
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(self.query(90 * 24).where(articles.c.id.in_(ids))).mappings()]

    def research_matches(self, hours, terms, **filters):
        if not terms:
            return []
        stmt = self.query(hours, **filters)
        matches = [search_document.contains(term, autoescape=True) for term in terms]
        score = sum(case((match, 1), else_=0) for match in matches)
        title_score = sum(case((articles.c.search_title.contains(term, autoescape=True), 1), else_=0)
                          for term in terms)
        stmt = stmt.where(or_(*matches)).order_by(score.desc(), title_score.desc(),
                                                  articles.c.published_at.desc(), articles.c.id).limit(96)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings()]

    def research_schema_exists(self):
        return inspect(self.engine).has_table(research_vectors.name)

    def research_index_samples(self, encoder, *, limit=1200, pending=False, **filters):
        joined = and_(articles.c.id == research_vectors.c.id, research_vectors.c.encoder == encoder,
                      articles.c.title == research_vectors.c.title, articles.c.description == research_vectors.c.description)
        stmt = self.query(**filters).outerjoin(research_vectors, joined)
        if pending:
            rank = func.row_number().over(partition_by=articles.c.source_id,
                order_by=(articles.c.published_at.desc(), articles.c.id)).label("publisher_rank")
            ranked = stmt.where(research_vectors.c.id.is_(None)).add_columns(rank).subquery()
            stmt = select(ranked).order_by(ranked.c.publisher_rank, ranked.c.published_at.desc(), ranked.c.id)
        else:
            stmt = stmt.where(research_vectors.c.id.is_not(None)).with_only_columns(
                articles.c.id, research_vectors.c.embedding).order_by(articles.c.published_at.desc(), articles.c.id)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt.limit(limit)).mappings()]

    def save_research_vectors(self, encoder, rows):
        if rows:
            with self.engine.begin() as conn:
                stmt = self.insert(research_vectors)
                conn.execute(stmt.on_conflict_do_update(index_elements=[research_vectors.c.id],
                    set_={key: stmt.excluded[key] for key in ("encoder", "title", "description", "embedding")}),
                    [{"id": row["id"], "title": row["title"], "description": row["description"],
                      "encoder": encoder, "embedding": embedding} for row, embedding in rows])
                from app import vector_search
                vector_search.upsert(self, encoder, rows, conn=conn)

    def research_vector(self, row, encoder):
        with self.engine.connect() as conn:
            return conn.scalar(select(research_vectors.c.embedding).where(research_vectors.c.id == row["id"],
                research_vectors.c.encoder == encoder, research_vectors.c.title == row["title"],
                research_vectors.c.description == row["description"]))

    def article(self, ident):
        with self.engine.connect() as conn:
            row = conn.execute(self.query(90 * 24).where(articles.c.id == ident)).mappings().first()
            result = dict(row) if row else None
        return self.with_reading_access([result], include_body=True)[0] if result else None

    def article_feed_ids(self, ident):
        self.ensure_feed_state_schema()
        stmt = select(article_feeds.c.source_id).outerjoin(sources, article_feeds.c.source_id == sources.c.id).where(
            article_feeds.c.article_id == ident, sources.c.enabled.is_not(False))
        with self.engine.connect() as conn:
            return set(conn.scalars(stmt))

    def related_candidates(self, ident, terms):
        if not terms:
            return []
        stmt = self.query(30 * 24).where(articles.c.id != ident)
        matches = [or_(articles.c.search_title.contains(term, autoescape=True),
                       articles.c.search_description.contains(term, autoescape=True)) for term in terms]
        score = sum(case((match, 1), else_=0) for match in matches)
        stmt = stmt.where(or_(*matches)).order_by(score.desc(), articles.c.published_at.desc(), articles.c.id.desc()).limit(200)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings()]

    def world_candidates(self, hours, source_ids, *, topic="all", region="", language="", coverage="", subject="",
                         source="all", publisher="", kind="all", query="", interests=None):
        # Limit each publisher within each topic so high-volume feeds cannot crowd out regional ones.
        order = [articles.c.published_at.desc(), articles.c.id.desc()]
        if interests is not None:
            # Scale the preference weights to match the final ranker's search-score contribution.
            boosts = [search_rank(query)] if query else []
            if interests.authors:
                boosts.append(case((articles.c.author_key.in_(interests.authors), 28), else_=0))
            if interests.sources:
                preferred = or_(articles.c.source_id.in_(interests.sources), articles.c.source.in_(interests.sources))
                boosts.append(case((preferred, 16), else_=0))
            if interests.subjects:
                subject_match = or_(*(articles.c.subject_keys.contains(f"|{key}|", autoescape=True)
                                      for key in interests.subjects))
                boosts.append(case((subject_match, 16), else_=0))
            feedback = getattr(interests, "feedback", None)
            if feedback and feedback.companies:
                company_match = or_(*(articles.c.title.icontains(name, autoescape=True) for name in feedback.companies))
                boosts.append(case((company_match, 25), else_=0))
            if boosts:
                order.insert(0, sum(boosts).desc())
        # Keep material developments in the candidate pool even during high-volume publication bursts.
        signal_match = or_(*(articles.c.search_title.contains(term, autoescape=True) for term in MATERIAL_TERMS))
        recent_signal = and_(signal_match, articles.c.published_at >= (datetime.now(UTC) - timedelta(hours=72)).isoformat())
        rank = func.row_number().over(partition_by=(articles.c.topic, articles.c.source_id),
            order_by=[case((recent_signal, 1), else_=0).desc(), *order]).label("topic_rank")
        candidates = self.query(hours, source=source, publisher=publisher, kind=kind, query=query,
                                source_ids=source_ids, topic=topic, region=region,
                                language=language, coverage=coverage, subject=subject)
        if interests and interests.exclude_ids:
            candidates = candidates.where(articles.c.id.not_in(interests.exclude_ids))
        if interests and (feedback := getattr(interests, "feedback", None)) and feedback.muted_topics:
            candidates = candidates.where(articles.c.topic.not_in(feedback.muted_topics))
        ranked = candidates.add_columns(rank).subquery()
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(select(ranked).where(ranked.c.topic_rank <= 10)).mappings()]

    def headline_candidates(self, hours, *, include_primary=False, per_source=30):
        providers = [s.id for s in BY_ID.values() if s.coverage in (
            {"reporting", "publisher", "advisory", "release"} if include_primary else {"reporting"})]
        important = or_(*(articles.c.search_title.contains(term, autoescape=True) for term in MATERIAL_TERMS))
        rank = func.row_number().over(partition_by=articles.c.source_id,
            order_by=(case((important, 1), else_=0).desc(), articles.c.published_at.desc(), articles.c.id.desc())).label("publisher_rank")
        release_ids = [s.id for s in BY_ID.values() if s.coverage == "release"]
        ranked = self.query(hours).where(articles.c.source_id.in_(providers),
            or_(articles.c.source_id.not_in(release_ids), important)).add_columns(rank).subquery()
        # A high-volume publisher cannot crowd quieter regional sources out of selection.
        with self.engine.connect() as conn:
            rows = conn.execute(select(ranked).where(ranked.c.publisher_rank <= per_source)).mappings()
            return [{key: value for key, value in row.items() if key != "publisher_rank"} for row in rows]

    def feed_diagnostics(self):
        self.ensure_feed_state_schema()
        with self.engine.connect() as conn:
            return {row["id"]: dict(row) for row in conn.execute(select(feed_diagnostics)).mappings()}

    def source_health_history(self, source_id, hours=24):
        self.ensure_feed_state_schema()
        conditions = (feed_checks.c.source_id == source_id, feed_checks.c.checked >= time.time() - hours * 3600)
        with self.engine.connect() as conn:
            totals = conn.execute(select(func.count().label("checks"),
                func.sum(case((feed_checks.c.available.is_(True), 1), else_=0)).label("successful"),
                func.avg(feed_checks.c.duration_ms).label("average_duration_ms")).where(*conditions)).mappings().one()
            recent = [dict(row) for row in conn.execute(select(feed_checks).where(*conditions)
                .order_by(feed_checks.c.checked.desc()).limit(50)).mappings()]
            return {**dict(totals), "recent": recent, "hours": hours}

    def source_article_urls(self, source_id):
        stmt = self.query(2160).where(or_(articles.c.source_id == source_id, articles.c.id.in_(
            select(article_feeds.c.article_id).where(article_feeds.c.source_id == source_id))))
        self.ensure_feed_state_schema()
        with self.engine.connect() as conn:
            return {row["url"] for row in conn.execute(stmt).mappings()}

    def coverage_counts(self):
        stmt = self.query(24).subquery()
        with self.engine.connect() as conn:
            return dict(conn.execute(select(stmt.c.topic, func.count()).group_by(stmt.c.topic)).all())

    def subject_counts(self, keys, hours=168):
        """Stories per subject over a window in one scan; subject keys are stored as |key| tokens."""
        if not keys:
            return {}
        stmt = self.query(hours).subquery()
        columns = [func.coalesce(func.sum(case((stmt.c.subject_keys.contains(f"|{key}|", autoescape=True), 1), else_=0)), 0)
                   for key in keys]
        with self.engine.connect() as conn:
            row = conn.execute(select(*columns)).one()
        return {key: int(value or 0) for key, value in zip(keys, row)}

    def lookup_url(self, url):
        from app.news import canonical_url
        canonical = canonical_url(url)
        parts = urlsplit(canonical)
        alternate = canonical.replace(parts.netloc, parts.netloc.removeprefix("www.") if parts.netloc.startswith("www.")
                                      else "www." + parts.netloc, 1)
        stmt = self.query(2160).where(or_(articles.c.url.in_((canonical, alternate)),
            articles.c.metadata_json.contains(canonical, autoescape=True),
            articles.c.metadata_json.contains(alternate, autoescape=True)))
        with self.engine.connect() as conn:
            matched = []
            for row in conn.execute(stmt.limit(50)).mappings():
                article = restore_metadata(row)
                try:
                    if any(canonical_url(value) in (canonical, alternate) for value in
                           (article["url"], article.get("original_url", "")) if value):
                        matched.append(article)
                except ValueError:
                    continue
            return matched[:10]

    def candidates(self, hours, source_ids, terms, *, topic="all", region="", language="", coverage="", subject=""):
        stmt = self.query(hours, source_ids=source_ids, topic=topic, region=region, language=language, coverage=coverage,
                          subject=subject)
        order = (articles.c.published_at.desc(), articles.c.id.desc())
        with self.engine.connect() as conn:
            recent = conn.execute(stmt.order_by(*order).limit(150)).mappings().all()
            if terms:
                # Include older matches; rank the bounded union in Python.
                ranked = conn.execute(stmt.where(or_(*(or_(
                    articles.c.search_title.contains(term, autoescape=True),
                    articles.c.search_description.contains(term, autoescape=True),
                ) for term in terms))).order_by(*order).limit(300)).mappings().all()
                return list({r["id"]: dict(r) for r in [*recent, *ranked]}.values())
            return [dict(r) for r in recent]

    def curiosity_candidates(self, source_ids, *, hours=90 * 24, limit=200):
        """Return a bounded set of archived engineering/research excerpts, without refreshing feeds."""
        if not source_ids:
            return []
        stmt = self.query(hours).where(articles.c.source_id.in_(tuple(source_ids)))
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(
                stmt.order_by(articles.c.published_at.desc(), articles.c.id.desc()).limit(max(1, min(limit, 500)))
            ).mappings()]

    def ensure_curiosity_schema(self):
        if self._curiosity_schema_ready:
            return
        with self._schema_lock, self.engine.begin() as conn:
            missing = [table for table in (mail_curiosity, curiosity_library) if not inspect(conn).has_table(table.name)]
            if missing:
                if self.engine.dialect.name == "postgresql":
                    conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                    conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
                for table in missing:
                    table.create(conn, checkfirst=True)
        self._curiosity_schema_ready = True

    def keep_curiosity_cards(self, cards, *, limit=300):
        """Save public card snapshots (title, link, summary, labels) and keep the best ``limit``."""
        if not cards:
            return
        self.ensure_curiosity_schema()
        now = time.time()
        with self.engine.begin() as conn:
            for card, score in cards:
                stmt = self.insert(curiosity_library).values(id=card["id"][:64], payload=json.dumps(card), score=int(score), saved=now)
                conn.execute(stmt.on_conflict_do_update(index_elements=[curiosity_library.c.id], set_={
                    "payload": stmt.excluded.payload, "score": stmt.excluded.score}))
            keep = select(curiosity_library.c.id).order_by(curiosity_library.c.score.desc(),
                                                           curiosity_library.c.saved.desc()).limit(limit)
            conn.execute(delete(curiosity_library).where(curiosity_library.c.id.not_in(keep.scalar_subquery())))

    def curiosity_library(self, limit=60):
        self.ensure_curiosity_schema()
        with self.engine.connect() as conn:
            rows = conn.execute(select(curiosity_library.c.payload).order_by(
                curiosity_library.c.score.desc(), curiosity_library.c.saved.desc()).limit(max(1, min(limit, 300)))).scalars()
            cards = []
            for payload in rows:
                try:
                    card = json.loads(payload)
                except ValueError:
                    continue
                if isinstance(card, dict) and isinstance(card.get("id"), str):
                    cards.append(card)
            return cards

    def curiosity_saved_card(self, ident):
        self.ensure_curiosity_schema()
        with self.engine.connect() as conn:
            payload = conn.scalar(select(curiosity_library.c.payload).where(curiosity_library.c.id == str(ident)[:64]))
        try:
            card = json.loads(payload) if payload else None
        except ValueError:
            return None
        return card if isinstance(card, dict) else None

    def curiosity_selection(self, mailbox):
        self.ensure_curiosity_schema()
        with self.engine.connect() as conn:
            payload = conn.scalar(select(mail_curiosity.c.payload).where(mail_curiosity.c.mailbox == mailbox))
        return json.loads(payload) if payload else []

    def save_curiosity_selection(self, mailbox, cards):
        """Atomically replace one verified mailbox's bounded card snapshots."""
        self.ensure_curiosity_schema()
        snapshot_fields = ("id", "title", "company", "publisher", "summary", "url", "tags", "read_minutes")
        snapshots = []
        for card in cards[:5]:
            snapshots.append({key: card[key] for key in snapshot_fields if key in card})
        with self.engine.begin() as conn:
            if not snapshots:
                conn.execute(delete(mail_curiosity).where(mail_curiosity.c.mailbox == mailbox))
                return
            stmt = self.insert(mail_curiosity).values(mailbox=mailbox, payload=json.dumps(snapshots), updated=time.time())
            conn.execute(stmt.on_conflict_do_update(index_elements=[mail_curiosity.c.mailbox], set_={
                "payload": stmt.excluded.payload, "updated": stmt.excluded.updated,
            }))

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
            advance = update(subscriptions).where(subscriptions.c.mailbox == bindparam("recipient_key")).values(
                next_run=bindparam("next_delivery"), claimed=0)
            skipped = [{"recipient_key": mailbox, "next_delivery": next_run}
                       for mailbox, message, next_run in pending if message is None]
            if skipped:
                conn.execute(advance, skipped)
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
            conn.execute(advance, [{"recipient_key": mailbox, "next_delivery": next_run}
                                   for mailbox, _, next_run in pending])
            for mailbox, message, _ in pending:
                if f"mail:{mailbox}" in eligible:
                    recipients.append(mailbox)
                    messages.append(message)
            if messages:
                from app import radar_store
                for mailbox, message in zip(recipients, messages, strict=True):
                    history = message.pop("_informa_event_history", None)
                    if history:
                        radar_store.reserve_events(conn, self, ident, mailbox, history)
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

    def claim_refresh(self, *, scheduled=False, scope="feed-refresh-lease", lease_seconds=180):
        """Claim one refresh across instances for longer than the function timeout."""
        now = time.time()
        expires = now + lease_seconds
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

    def feed_attempts(self, slot):
        with self.engine.connect() as conn:
            scopes = conn.scalars(select(limits.c.scope).where(
                limits.c.bucket == slot, limits.c.scope.startswith("feed-slot:")))
            return {scope.removeprefix("feed-slot:") for scope in scopes}

    def claim_feed_check(self, source_id, slot):
        """Reserve one publisher check before making a request, even across worker restarts."""
        claim = self.insert(limits).values(scope=f"feed-slot:{source_id}", bucket=slot, used=1, touched=time.time())
        with self.engine.begin() as conn:
            return conn.scalar(claim.on_conflict_do_nothing().returning(limits.c.scope)) is not None

    def feed_host_backoffs(self, now):
        with self.engine.connect() as conn:
            rows = conn.execute(select(limits.c.scope, limits.c.touched).where(limits.c.bucket == "backoff",
                limits.c.scope.startswith("feed-host:"), limits.c.touched > now))
            return {scope.removeprefix("feed-host:"): until for scope, until in rows}

    def defer_feed_host(self, host, until):
        pause = self.insert(limits).values(scope=f"feed-host:{host}", bucket="backoff", used=1, touched=until)
        with self.engine.begin() as conn:
            conn.execute(pause.on_conflict_do_update(index_elements=[limits.c.scope, limits.c.bucket],
                set_={"touched": pause.excluded.touched}, where=limits.c.touched < until))

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

    def ensure_mail_revocation_schema(self):
        if self._mail_revocations_ready:
            return
        with self._schema_lock, self.engine.begin() as conn:
            if not inspect(conn).has_table(mail_session_revocations.name):
                if self.engine.dialect.name == "postgresql":
                    conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                    conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
                mail_session_revocations.create(conn, checkfirst=True)
        self._mail_revocations_ready = True

    def mail_session_revoked(self, digest):
        self.ensure_mail_revocation_schema()
        with self.engine.connect() as conn:
            return conn.scalar(select(mail_session_revocations.c.digest).where(
                mail_session_revocations.c.digest == digest,
                mail_session_revocations.c.expires > time.time())) is not None

    def revoke_mail_session(self, digest, expires):
        self.ensure_mail_revocation_schema()
        with self.engine.begin() as conn:
            conn.execute(self.insert(mail_session_revocations).values(digest=digest, expires=expires)
                         .on_conflict_do_nothing())

    def discard_code(self, ident, mailbox):
        with self.engine.begin() as conn:
            conn.execute(delete(codes).where(codes.c.id == ident, codes.c.mailbox == mailbox))

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

    def reserve_delivery(self, ident, policies, *, windows=(), event_mailbox=None, event_history=None):
        """Atomically reserve recipient quota once for a preview and inbox."""
        try:
            with self.engine.begin() as conn:
                stmt = self.insert(deliveries).values(id=ident, created=time.time())
                if conn.scalar(stmt.on_conflict_do_nothing(index_elements=[deliveries.c.id]).returning(deliveries.c.id)) is not None:
                    self._admit_windows(conn, windows)
                    self._admit(conn, policies)
                    if event_mailbox and event_history:
                        from app import radar_store
                        radar_store.reserve_events(conn, self, ident, event_mailbox, event_history)
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
            from app import radar_store
            radar_store.accept_events(conn, self, ident)

    def delivery_status(self, ident):
        with self.engine.connect() as conn:
            row = conn.execute(select(deliveries).where(deliveries.c.id == ident)).first()
            if not row:
                return None
            state, updated = ("accepted" if row.provider_id else "unconfirmed"), row.created
            if row.provider_id:
                # Terminal outcomes take precedence over delayed, out-of-order webhooks.
                priority = {"email.sent": 0, "email.delivery_delayed": 1, "email.delivered": 2,
                            "email.failed": 3, "email.bounced": 4, "email.suppressed": 5, "email.complained": 6}
                events = conn.execute(select(mail_outcomes).where(mail_outcomes.c.provider_id == row.provider_id)).all()
                if events:
                    latest = max(events, key=lambda event: (priority.get(event.kind, -1), event.occurred_at))
                    state = latest.kind.removeprefix("email.")
                    updated = latest.occurred_at
            return {"status": state, "updated_at": datetime.fromtimestamp(updated, UTC).isoformat()}

    def mail_used(self, mailbox, bucket):
        with self.engine.connect() as conn:
            return conn.scalar(select(limits.c.used).where(
                limits.c.scope == f"mail:{mailbox}", limits.c.bucket == bucket)) or 0

    def record_mail_batch_events(self, ident, mailboxes):
        with self.engine.begin() as conn:
            from app import radar_store
            radar_store.accept_events(conn, self, ident, allowed_mailboxes=set(mailboxes))

    def get_summary(self, ident):
        with self.engine.connect() as conn:
            payload = conn.scalar(select(summaries.c.payload).where(summaries.c.id == ident))
        return json.loads(payload) if payload else None

    def save_summary(self, ident, payload, *, replace=False):
        with self.engine.begin() as conn:
            stmt = self.insert(summaries).values(id=ident, payload=json.dumps(payload), created=time.time())
            conn.execute(stmt.on_conflict_do_update(index_elements=[summaries.c.id],
                set_={"payload": stmt.excluded.payload, "created": stmt.excluded.created})
                if replace else stmt.on_conflict_do_nothing(index_elements=[summaries.c.id]))

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

    def record_mail_event(self, ident, kind, mailboxes, *, provider_id=None, occurred_at=None):
        with self.engine.begin() as conn:
            stmt = self.insert(mail_events).values(id=ident, kind=kind, received_at=time.time())
            inserted = conn.scalar(stmt.on_conflict_do_nothing().returning(mail_events.c.id))
            if not inserted:
                return
            if provider_id:
                conn.execute(self.insert(mail_outcomes).values(id=ident, provider_id=provider_id, kind=kind,
                    occurred_at=occurred_at or time.time(), received_at=time.time()).on_conflict_do_nothing())
            if not mailboxes:
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
        self.ensure_discovery_schema()
        self.ensure_feed_state_schema()
        now = time.time()
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        with self.engine.begin() as conn:
            # Repair any writes completed just before older deployments were drained.
            backfill_discovery(conn)
            for table, condition in (
                (codes, codes.c.expires < now), (previews, previews.c.expires < now),
                (limits, limits.c.touched < now - 7 * 86400), (deliveries, deliveries.c.created < now - 30 * 86400),
                (summaries, summaries.c.created < now - 90 * 86400), (articles, articles.c.published_at < cutoff),
                (mail_batches, mail_batches.c.created < now - 7 * 86400),
                (mail_events, mail_events.c.received_at < now - 30 * 86400),
                (mail_outcomes, mail_outcomes.c.received_at < now - 30 * 86400),
                (article_feeds, ~select(articles.c.id).where(articles.c.id == article_feeds.c.article_id).exists()),
                (feed_checks, feed_checks.c.checked < now - 7 * 86400),
            ):
                conn.execute(delete(table).where(condition))
            from app import event_intelligence, radar_store
            if getattr(self, "_event_tables_ready", False):
                event_intelligence.prune(conn, now)
            if getattr(self, "_radar_tables_ready", False):
                radar_store.prune(conn, now)
            if inspect(conn).has_table(research_vectors.name):
                conn.execute(delete(research_vectors).where(
                    ~select(articles.c.id).where(articles.c.id == research_vectors.c.id).exists()))
            if inspect(conn).has_table(mail_session_revocations.name):
                conn.execute(delete(mail_session_revocations).where(mail_session_revocations.c.expires <= now))


@lru_cache(maxsize=2)
def connect(url):
    return Store(url)


def get_store():
    url = os.getenv("NEWS_DATABASE_URL")
    return connect(url) if url else None
