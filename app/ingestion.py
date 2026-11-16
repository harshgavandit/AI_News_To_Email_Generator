"""Scheduled and admin-triggered refresh; browsing never waits on it with a store."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

from app.coverage import region_id
from app.news import FEED_WORKERS, read_feed
from app.sources import DEFAULT_SOURCES

FRESH_FOR = timedelta(minutes=45)


def refresh_sources(store, only=None, *, source_ids=None):
    state = store.source_state(include_archive=False)
    active = [s for s in DEFAULT_SOURCES if (only is None or s.id == only)
              and state.get(s.id, {}).get("enabled", s.enabled)
              and (source_ids is None or s.id in source_ids)]
    validators = store.current_feed_validators() if any(feed.integration == "rss" for feed in active) else {}
    with ThreadPoolExecutor(max_workers=FEED_WORKERS) as pool:
        futures = {}
        for source in active:
            saved = validators.get(source.id, {})
            if source.integration == "rss":
                # A targeted owner refresh requests a complete snapshot for recovery.
                cached = saved if only is None and saved.get("feed_url") == source.url else {}
                future = pool.submit(read_feed, source, validators=cached)
            else:
                future = pool.submit(read_feed, source)
            futures[future] = source
        for future in as_completed(futures):
            try:
                items, status = future.result()
            except Exception:
                # A malformed feed must not stop the other publishers from updating.
                items, status = [], {"available": False, "error": "parser_failed"}
            source = futures[future]
            store.ingest(source.id, items, status["available"], status.get("error"),
                         feed_url=source.url if source.integration == "rss" else None,
                         validators=status.get("validators"), unchanged=status.get("unchanged", False))
    if only is None and source_ids is None:
        store.prune()
    return source_catalog(store)


def source_catalog(store=None, *, include_archive=True):
    states = store.source_state(include_archive=include_archive) if store else {}
    cutoff = (datetime.now(UTC) - FRESH_FOR).isoformat()
    result = []
    for s in DEFAULT_SOURCES:
        state = states.get(s.id, {})
        feed = {**s.public(), "region_id": region_id(s.region), "enabled": state.get("enabled", s.enabled),
                "available": state.get("available"), "last_success": timestamp(state.get("last_success")),
                "checked_at": timestamp(state.get("checked")), "count": state.get("count", 0)}
        feed["latest_published_at"] = state.get("latest_published_at")
        feed["retained_count"] = state.get("retained_count", 0)
        if state.get("error"):
            feed["error"] = state["error"]
        feed["freshness"] = (source_freshness(feed, cutoff) if feed["enabled"] else "paused")
        result.append(feed)
    return result


def timestamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value else None


def source_freshness(feed, cutoff):
    if feed["available"] is False:
        return "failed"
    if not feed.get("last_success"):
        return "pending"
    return "stale" if feed["last_success"] < cutoff else "fresh"


def selected_feeds(catalog, *, source="all", publisher="", kind="all", region="", coverage="", language=""):
    return [feed for feed in catalog if feed["enabled"] and (source == "all" or source in (feed["id"], feed["source"]))
            and (not publisher or feed["id"] == publisher) and (kind == "all" or feed["kind"] == kind)
            and (not region or region_id(feed.get("region", "Global")) == region)
            and (not coverage or feed.get("coverage") == coverage)
            and (not language or feed.get("language") == language)]


def feed_freshness(catalog, **filters):
    active = selected_feeds(catalog, **filters)
    cutoff = (datetime.now(UTC) - FRESH_FOR).isoformat()
    counts = dict(enabled=len(active), fresh=0, stale=0, failed=0, pending=0)
    for feed in active:
        counts[source_freshness(feed, cutoff)] += 1

    if counts["fresh"]:
        status = "fresh" if counts["fresh"] == len(active) else "degraded"
    elif counts["failed"] or counts["stale"]:
        status = "stale"
    else:
        status = "pending"
    return {"status": status, "counts": counts,
            "checked_at": max((s.get("checked_at") or "" for s in active), default="") or None,
            "last_success": max((s.get("last_success") or "" for s in active), default="") or None}
