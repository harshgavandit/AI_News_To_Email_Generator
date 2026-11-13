"""Scheduled and admin-triggered refresh; browsing never waits on it with a store."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.news import read_feed
from app.sources import DEFAULT_SOURCES


def refresh_sources(store, only=None):
    state = store.source_state()
    active = [s for s in DEFAULT_SOURCES if (only is None or s.id == only)
              and state.get(s.id, {}).get("enabled", s.enabled)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for s, (items, status) in zip(active, pool.map(read_feed, active)):
            store.ingest(s.id, items, status["available"], status.get("error"))
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
