"""How a grouped story was covered: who reported first, how many publishers, and from which regions.

Used on story cards (Reading Room), the "Compare coverage" dialog and development pages. It only reads
groupings the intelligence job already made; grouping matching headlines does not mean publishers agree.
"""
from datetime import datetime
import logging

from sqlalchemy import select

from app.coverage import REGION_LABELS, region_id
from app.launch_store import articles
from app.sources import BY_ID

logger = logging.getLogger(__name__)
MAX_PUBLISHERS_LISTED = 8


def distinct_stories(rows):
    """Keep ranked representatives while preserving materially different reports."""
    from app.story_coverage import frontpage_match, headline

    kept, headlines = [], []
    for row in rows:
        candidate = headline(row, include_status=True, frontpage=True)
        if not any(frontpage_match(candidate, previous) for previous in headlines):
            kept.append(row)
            headlines.append(candidate)
    return kept


def _moment(value):
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else None


def coverage_summary(sources):
    """``sources``: dicts with ``publisher``, ``published_at`` and ``source_id`` (or ``region``/``publisher_family``)."""
    by_family = {}
    for source in sources:
        info = BY_ID.get(source.get("source_id"))
        family = source.get("publisher_family") or (info.publisher_family if info else source.get("publisher"))
        moment = _moment(source.get("published_at") or source.get("publishedAt"))
        if not family:
            continue
        current = by_family.get(family)
        if current is None or (moment and (current["moment"] is None or moment < current["moment"])):
            region = source.get("region_id") or region_id(info.region if info else source.get("region") or "Global")
            by_family[family] = {"publisher": source.get("publisher") or source.get("sourceName") or (info.label if info else family),
                                 "moment": moment, "region": region if region in REGION_LABELS else "Global"}
    entries = sorted(by_family.values(), key=lambda item: (item["moment"] is None, item["moment"] or datetime.max))
    if not entries:
        return None
    first = entries[0]
    second = entries[1] if len(entries) > 1 else None
    lead = (int((second["moment"] - first["moment"]).total_seconds() // 60)
            if second and first["moment"] and second["moment"] else None)
    regions = {}
    for item in entries:
        regions[item["region"]] = regions.get(item["region"], 0) + 1
    return {"publishers": len(entries),
            "names": [item["publisher"] for item in entries[:MAX_PUBLISHERS_LISTED]],
            "first_reported_by": first["publisher"] if first["moment"] else None,
            "first_reported_at": first["moment"].isoformat() if first["moment"] else None,
            "lead_minutes": lead,
            "regions": [{"id": key, "label": REGION_LABELS[key], "count": count}
                        for key, count in sorted(regions.items(), key=lambda pair: (-pair[1], pair[0]))]}


def annotate_articles(store, rows):
    """Add grouped-coverage facts to Reading Room stories that belong to a multi-publisher development."""
    from app import event_intelligence
    ids = [row["id"] for row in rows if row.get("id")]
    if not ids or not event_intelligence.ready(store):
        return rows
    items = event_intelligence.event_items
    try:
        with store.engine.connect() as conn:
            links = dict(conn.execute(select(items.c.article_id, items.c.event_id).where(items.c.article_id.in_(ids))).all())
            if not links:
                return rows
            members = conn.execute(select(items.c.event_id, articles.c.source_id, articles.c.publisher, articles.c.published_at)
                                   .join(articles, articles.c.id == items.c.article_id)
                                   .where(items.c.event_id.in_(set(links.values()))).limit(2000)).mappings().all()
    except Exception as error:  # noqa: BLE001 - stories still render without coverage facts
        logger.warning("story_groups_unavailable error_type=%s", type(error).__name__)
        return rows
    grouped = {}
    for member in members:
        grouped.setdefault(member["event_id"], []).append(dict(member))
    summaries = {event: coverage_summary(group) for event, group in grouped.items()}
    for row in rows:
        event = links.get(row.get("id"))
        summary = summaries.get(event)
        if not summary or summary["publishers"] < 2:
            continue
        row["development_id"] = event
        row["coverage_summary"] = summary
        if (row.get("coverage_count") or 0) < summary["publishers"]:
            row["coverage_count"] = summary["publishers"]
            row["coverage_publishers"] = summary["names"]
    return rows
