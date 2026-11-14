"""Scheduled and admin-triggered refresh; browsing never waits on it with a store."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

from app.news import read_feed
from app.sources import DEFAULT_SOURCES

FRESH_FOR = timedelta(minutes=45)


def refresh_sources(store, only=None, *, failed_only=False):
    state = store.source_state()
    active = [s for s in DEFAULT_SOURCES if (only is None or s.id == only)
              and state.get(s.id, {}).get("enabled", s.enabled)
              and (not failed_only or state.get(s.id, {}).get("available") is False)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(read_feed, source): source for source in active}
        for future in as_completed(futures):
            try:
                items, status = future.result()
            except Exception:
                # A malformed feed must not stop the other publishers from updating.
                items, status = [], {"available": False, "error": "parser_failed"}
            store.ingest(futures[future].id, items, status["available"], status.get("error"))
    store.prune()
    return source_catalog(store)


def source_catalog(store=None):
    states = store.source_state() if store else {}
    result = []
    for s in DEFAULT_SOURCES:
        state = states.get(s.id, {})
        result.append({**s.public(), "enabled": state.get("enabled", s.enabled),
                       "available": state.get("available"),
                       "last_success": timestamp(state.get("last_success")),
                       "checked_at": timestamp(state.get("checked")), "count": state.get("count", 0)})
    return result


def timestamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value else None


def feed_freshness(catalog, *, source="all", publisher="", kind="all"):
    active = [s for s in catalog if s["enabled"] and (source == "all" or source in (s["id"], s["source"]))
              and (not publisher or s["id"] == publisher) and (kind == "all" or s["kind"] == kind)]
    cutoff = (datetime.now(UTC) - FRESH_FOR).isoformat()
    counts = dict(enabled=len(active), fresh=0, stale=0, failed=0, pending=0)
    for feed in active:
        if feed["available"] is False:
            counts["failed"] += 1
        elif not feed.get("last_success"):
            counts["pending"] += 1
        elif feed["last_success"] < cutoff:
            counts["stale"] += 1
        else:
            counts["fresh"] += 1

    if counts["fresh"]:
        status = "fresh" if counts["fresh"] == len(active) else "degraded"
    elif counts["failed"] or counts["stale"]:
        status = "stale"
    else:
        status = "pending"
    return {"status": status, "counts": counts,
            "checked_at": max((s.get("checked_at") or "" for s in active), default="") or None,
            "last_success": max((s.get("last_success") or "" for s in active), default="") or None}
