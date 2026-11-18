"""Show observed check health without claiming complete coverage."""
from app.ingestion import feed_freshness, selected_feeds, source_catalog


def coverage_snapshot(store, *, topics=(), source_ids=(), linked_only=False, filters=None):
    catalog = source_catalog(store, include_archive=False)
    linked = set(source_ids)
    scoped = (set(topics) - {"", "all"}) if not linked_only else set()
    if linked_only:
        relevant = [row for row in catalog if row["id"] in linked]
    else:
        relevant = [row for row in catalog if not scoped or row["topic"] in scoped or row["id"] in linked]
        relevant = selected_feeds(relevant, **(filters or {}))
    result = feed_freshness(relevant)
    result["scope"] = ("Feeds linked to this development" if linked_only else
                       "Selected topic and evidence feeds" if scoped else
                       "Selected archive feeds" if any(value not in {"", "all"} for value in (filters or {}).values()) else
                       "Archive-wide feed checks")
    if linked_only:
        result["feeds"] = [{key: row[key] for key in ("id", "label", "freshness", "checked_at", "last_success")}
                           for row in relevant]
    return result
