"""Persistent source-linked developments and publication/revision timelines.

Grouping is evidence linkage, not a claim that publishers agree. Public reads
never fetch a URL or run a model. The existing intelligence worker maintains it.
"""
from datetime import UTC, datetime
import hashlib
import json
import time

from sqlalchemy import Column, Float, Index, Integer, String, Table, Text, delete, inspect, select, update

from app.coverage import public_article
from app.discovery import search_terms, search_text
from app.intelligence import GENERIC_TERMS, references
from app.launch_store import articles, schema, search_document
from app.material_changes import LABELS, change_kind
from app.sources import BY_ID
from app.story_coverage import coverage_match, headline

events = Table("brief_intelligence_events", schema,
    Column("id", String(32), primary_key=True), Column("anchor_id", String(40), nullable=False),
    Column("title", Text, nullable=False), Column("topic", String(32), nullable=False),
    Column("revision", Integer, nullable=False, default=1),
    Column("created", Float, nullable=False), Column("updated", Float, nullable=False, index=True))
event_items = Table("brief_event_items", schema,
    Column("article_id", String(40), primary_key=True), Column("event_id", String(32), nullable=False, index=True),
    Column("fingerprint", String(64), nullable=False), Column("observed", Float, nullable=False))
event_keys = Table("brief_event_keys", schema,
    Column("key", String(100), primary_key=True), Column("event_id", String(32), primary_key=True))
event_updates = Table("brief_event_updates", schema,
    Column("id", String(64), primary_key=True), Column("event_id", String(32), nullable=False),
    Column("article_id", String(40), nullable=False), Column("observed", Float, nullable=False),
    Column("published_at", String(40), nullable=False), Column("title", Text, nullable=False),
    Column("excerpt", Text, nullable=False), Column("reason", String(32), nullable=False))
Index("brief_event_updates_timeline", event_updates.c.event_id, event_updates.c.observed)
event_revisions = Table("brief_event_update_revisions", schema,
    Column("update_id", String(64), primary_key=True), Column("event_id", String(32), nullable=False),
    Column("revision", Integer, nullable=False))
Index("brief_event_revision_lookup", event_revisions.c.event_id, event_revisions.c.revision)
TABLES = (events, event_items, event_keys, event_updates)
STOPS = GENERIC_TERMS | frozenset("new announces announced launches launched unveils latest says introduces introducing report reports".split())


def ready(store):
    if not hasattr(store, "_event_tables_ready"):
        store._event_tables_ready = all(inspect(store.engine).has_table(table.name) for table in TABLES)
    return store._event_tables_ready


def fingerprint(row):
    return hashlib.sha256(json.dumps([row["title"], row.get("description", "")], ensure_ascii=False).encode()).hexdigest()


def revisions_ready(store):
    if not getattr(store, "_event_revisions_ready", False):
        store._event_revisions_ready = inspect(store.engine).has_table(event_revisions.name)
    return store._event_revisions_ready


def keys_for(row):
    tokens = [word for word in search_text(row["title"]).split() if len(word) > 3 and word not in STOPS and not word.isdecimal()]
    return sorted({*("ref:" + value.lower() for value in references(row)), *tokens})[:24]


def event_score(row, candidate):
    if row["id"] == candidate["id"]:
        return 1.0
    left, right = BY_ID.get(row["source_id"]), BY_ID.get(candidate["source_id"])
    if left and right and left.coverage == right.coverage == "status" and left.id != right.id:
        return 0
    if match := coverage_match(headline(row, include_status=True), headline(candidate, include_status=True)):
        return match[0]
    # Official releases and tutorials are not different reports of one event.
    if not left or not right or left.coverage not in {"reporting", "publisher", "advisory"} or right.coverage not in {"reporting", "publisher", "advisory"}:
        return 0
    if left.language != right.language:
        return 0
    words, other = set(keys_for(row)), set(keys_for(candidate))
    overlap = words & other
    # A changed figure can be an update, but sharing a company name cannot.
    if len(overlap) >= 5 and len(overlap) / max(1, min(len(words), len(other))) >= .8:
        return len(overlap) / max(1, len(words | other))
    return 0


def observe(store, row, *, now=None, semantic_ids=()):
    now = now or time.time()
    stamp = fingerprint(row)
    keys = keys_for(row)
    track_revisions = revisions_ready(store)
    with store.engine.begin() as conn:
        old = conn.execute(select(event_items).where(event_items.c.article_id == row["id"])).mappings().first()
        if old and old["fingerprint"] == stamp:
            conn.execute(update(event_items).where(event_items.c.article_id == row["id"]).values(observed=now))
            return old["event_id"], False
        event_id = old["event_id"] if old else None
        if not event_id and keys:
            recent = now - 7 * 86400
            candidates = conn.execute(select(events.c.id, articles).join(event_keys, event_keys.c.event_id == events.c.id)
                .join(articles, articles.c.id == events.c.anchor_id).where(event_keys.c.key.in_(keys), events.c.updated >= recent)
                .distinct().limit(40)).mappings().all()
            ranked = [(event_score(row, candidate), candidate["id"]) for candidate in candidates]
            qualified = [(score, ident) for score, ident in ranked if score >= .5]
            if qualified:
                event_id = max(qualified)[1]
        if not event_id and semantic_ids:
            # A semantic match must still have corroborating headline evidence.
            candidates = conn.execute(select(event_items.c.event_id, articles).join(articles,
                articles.c.id == event_items.c.article_id).where(event_items.c.article_id.in_(semantic_ids)).limit(12)).mappings()
            for candidate in candidates:
                if event_score(row, candidate) >= .5:
                    event_id = candidate["event_id"]
                    break
        new_event = not event_id
        event_id = event_id or hashlib.sha256(("event:" + row["id"]).encode()).hexdigest()[:32]
        significant = True
        reason = "first_report"
        if new_event:
            stmt = store.insert(events).values(id=event_id, anchor_id=row["id"], title=row["title"],
                topic=row.get("topic") or "industry", revision=1, created=now, updated=now)
            conn.execute(stmt.on_conflict_do_nothing())
        else:
            previous = conn.execute(select(event_updates, articles.c.source_id)
                .join(articles, articles.c.id == event_updates.c.article_id)
                .where(event_updates.c.event_id == event_id)
                .order_by(event_updates.c.observed.desc(), event_updates.c.id).limit(40)).mappings().all()
            reason = change_kind(row, previous, same_article=bool(old))
            significant = reason not in {"source_revision", "additional_reporting"}
            if significant:
                conn.execute(update(events).where(events.c.id == event_id)
                             .values(updated=now, revision=events.c.revision + 1))
        stmt = store.insert(event_items).values(article_id=row["id"], event_id=event_id, fingerprint=stamp, observed=now)
        conn.execute(stmt.on_conflict_do_update(index_elements=[event_items.c.article_id],
            set_={"fingerprint": stamp, "observed": now}))
        for key in keys:
            conn.execute(store.insert(event_keys).values(key=key, event_id=event_id).on_conflict_do_nothing())
        update_id = hashlib.sha256(f"{row['id']}:{stamp}:{now}".encode()).hexdigest()
        conn.execute(store.insert(event_updates).values(id=update_id,
            event_id=event_id, article_id=row["id"], observed=now, published_at=row["published_at"],
            title=row["title"], excerpt=public_article(row)["cleanSummary"],
            reason=reason).on_conflict_do_nothing())
        if significant and track_revisions:
            revision = conn.execute(select(events.c.revision).where(events.c.id == event_id)).scalar_one()
            conn.execute(store.insert(event_revisions).values(update_id=update_id, event_id=event_id,
                revision=revision).on_conflict_do_nothing())
    return event_id, True


def sync(store, *, maximum=96):
    if not ready(store):
        return {"event_status": "migration_required", "events_indexed": 0}
    lease = store.claim_refresh(scope="intelligence-events")
    if lease is None:
        return {"event_status": "already_started", "events_indexed": 0}
    try:
        # Recent uncaptured articles first; revisions get a separate bounded pass.
        stmt = store.query(168).outerjoin(event_items, event_items.c.article_id == articles.c.id)
        with store.engine.connect() as conn:
            rows = conn.execute(stmt.where(event_items.c.article_id.is_(None)).order_by(
                articles.c.published_at.desc(), articles.c.id).limit(maximum)).mappings().all()
            revised = conn.execute(stmt.where(event_items.c.article_id.is_not(None)).order_by(
                event_items.c.observed).limit(24)).mappings().all()
        indexed = 0
        for row in [*rows, *revised]:
            _, changed = observe(store, dict(row))
            indexed += changed
        return {"event_status": "updated" if indexed else "current", "events_indexed": indexed}
    finally:
        store.finish_refresh(lease, scope="intelligence-events")


def version_for(rows):
    """Content identity changes for revisions and new evidence, never for wall time."""
    return hashlib.sha256(json.dumps(sorted((row["id"], fingerprint(row)) for row in rows)).encode()).hexdigest()[:32]


def development_for_article(store, article_id):
    if not ready(store):
        return None
    with store.engine.connect() as conn:
        return conn.scalar(select(event_items.c.event_id).where(event_items.c.article_id == article_id))


def catalog(store, *, hours=168, limit=80, topic="all", event_ids=(), query=""):
    if not ready(store):
        return []
    with store.engine.connect() as conn:
        scope = events.c.id.in_(event_ids) if event_ids else events.c.updated >= time.time() - hours * 3600
        stmt = select(events).where(scope, *([events.c.topic == topic] if topic != "all" else []))
        if query:
            terms = search_terms(query) or (search_text(query),)
            if not any(terms):
                return []
            matches = store.query(2160).join(event_items, event_items.c.article_id == articles.c.id)
            matches = matches.with_only_columns(event_items.c.event_id, maintain_column_froms=True).where(
                *(search_document.contains(term, autoescape=True) for term in terms))
            stmt = stmt.where(events.c.id.in_(matches))
        chosen = conn.execute(stmt.order_by(events.c.updated.desc(), events.c.id).limit(limit)).mappings().all()
        ids = [row["id"] for row in chosen]
        if not ids:
            return []
        # Event freshness is based on a new report/revision, so its anchor article
        # may be older than the selected window. Keep retained evidence available.
        rows = conn.execute(store.query(2160).join(event_items,
            event_items.c.article_id == articles.c.id).add_columns(event_items.c.event_id)
            .where(event_items.c.event_id.in_(ids))).mappings().all()
    groups = {ident: [] for ident in ids}
    for row in rows:
        groups[row["event_id"]].append(dict(row))
    result = []
    for event in chosen:
        material = sorted(groups[event["id"]], key=lambda row: (row["published_at"], row["id"]), reverse=True)
        if not material:
            continue
        result.append({"id": event["id"], "title": material[0]["title"], "topic": event["topic"],
            "created_at": datetime.fromtimestamp(event["created"], UTC).isoformat(),
            "updated_at": datetime.fromtimestamp(event["updated"], UTC).isoformat(),
            "version": version_for(material), "digest_version": str(event["revision"]),
            "source_count": len({BY_ID[row["source_id"]].publisher_family for row in material}),
            "article_count": len(material), "articles": [public_article(row) for row in material[:12]],
            "basis": "Related publisher coverage; grouping does not establish agreement."})
    return result


def timeline(store, ident, since=None, *, observed_since=None):
    if not ready(store):
        return None
    track_revisions = revisions_ready(store)
    with store.engine.connect() as conn:
        event = conn.execute(select(events).where(events.c.id == ident)).mappings().first()
        if not event:
            return None
        retained = {row["id"]: public_article(row) for row in conn.execute(store.query(2160).join(event_items,
            event_items.c.article_id == articles.c.id).where(event_items.c.event_id == ident)).mappings()}
        updates = conn.execute(select(event_updates).where(event_updates.c.event_id == ident,
            event_updates.c.article_id.in_(retained)).order_by(event_updates.c.observed.desc()).limit(40)).mappings()
        def entry(row):
            return {**dict(row), "source": retained[row["article_id"]],
                    "change_label": LABELS.get(row["reason"], "Publisher update")}

        entries = [entry(row) for row in updates]
        changes = []
        if track_revisions and (since is not None or observed_since is not None):
            cutoff = (event_revisions.c.revision > since if since is not None
                      else event_updates.c.observed > observed_since)
            revisions = conn.execute(select(event_updates, event_revisions.c.revision).join(event_revisions,
                event_revisions.c.update_id == event_updates.c.id).where(event_revisions.c.event_id == ident,
                cutoff, event_updates.c.article_id.in_(retained))
                .order_by(event_revisions.c.revision.desc(), event_updates.c.observed.desc()).limit(5)).mappings()
            changes = [entry(row) for row in revisions]
    if not retained:
        return None
    latest_material = next((item for item in entries if item["reason"] not in {"additional_reporting", "source_revision"}), None)
    return {"id": ident, "title": event["title"], "entries": entries, "changes": changes,
            "latest_material": latest_material, "topic": event["topic"],
            "revision": str(event["revision"]),
            "notice": "Publication and observed revision history. Additional reporting may repeat existing facts."}


def prune(conn, now):
    expired = select(events.c.id).where(events.c.updated < now - 90 * 86400)
    for table in (event_keys, event_items, event_updates):
        conn.execute(delete(table).where(table.c.event_id.in_(expired)))
    conn.execute(delete(events).where(events.c.updated < now - 90 * 86400))
    retained_articles = select(articles.c.id)
    conn.execute(delete(event_items).where(~event_items.c.article_id.in_(retained_articles)))
    conn.execute(delete(event_updates).where(~event_updates.c.article_id.in_(retained_articles)))
    if inspect(conn).has_table(event_revisions.name):
        conn.execute(delete(event_revisions).where(~event_revisions.c.update_id.in_(select(event_updates.c.id))))
