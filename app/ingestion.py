"""Scheduled and admin-triggered refresh; browsing never waits on it with a store."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta, timezone
from collections import Counter, defaultdict
import threading
import time
import os
from urllib.parse import urlsplit

from app.coverage import region_id
from app.news import FEED_WORKERS, read_feed
from app.sources import DEFAULT_SOURCES

FRESH_FOR = timedelta(minutes=45)
INDIA_TIME = timezone(timedelta(hours=5, minutes=30))
DAILY_REFRESH_GRACE = timedelta(minutes=45)
HOST_GATES = defaultdict(lambda: threading.Semaphore(2))


def refresh_mode():
    return "daily" if os.getenv("FEED_REFRESH_MODE", "").casefold() == "daily" else "adaptive"


def morning_refresh_at(now):
    return now.astimezone(INDIA_TIME).replace(hour=8, minute=0, second=0, microsecond=0).astimezone(UTC)


def daily_refresh_plan(state, morning, now):
    """One scheduled check per enabled source per India calendar day."""
    pending = {source.id for source in DEFAULT_SOURCES
               if state.get(source.id, {}).get("enabled", source.enabled)
               and (state.get(source.id, {}).get("checked") or 0) < morning.timestamp()}
    ready = {source_id for source_id in pending
             if (state.get(source_id, {}).get("retry_at") or 0) <= now.timestamp()}
    return ready, len(pending - ready)


def refresh_plan(state, *, only=None, source_ids=None, due_only=False, maximum=None, now=None, per_host=6):
    now = now or datetime.now(UTC).timestamp()
    candidates = [source for source in DEFAULT_SOURCES if (only is None or source.id == only)
        and state.get(source.id, {}).get("enabled", source.enabled)
        and (state.get(source.id, {}).get("retry_at") or 0) <= now
        and (source_ids is None or source.id in source_ids)
        and (not due_only or state.get(source.id, {}).get("available") is False
             or (state.get(source.id, {}).get("checked") or 0) + source.poll_minutes * 60 <= now)]
    # Never-checked feeds first, then the most overdue. Stable ordering prevents starvation.
    candidates.sort(key=lambda source: ((state.get(source.id, {}).get("checked") or 0) + source.poll_minutes * 60, source.id))
    if maximum is None:
        return candidates
    selected, hosts = [], Counter()
    for source in candidates:
        host = urlsplit(source.url).hostname.removeprefix("www.")
        if hosts[host] >= per_host:
            continue
        selected.append(source)
        hosts[host] += 1
        if len(selected) == maximum:
            break
    return selected


def timed_read(source, **kwargs):
    started = time.monotonic()
    with HOST_GATES[urlsplit(source.url).hostname.removeprefix("www.")]:
        items, status = read_feed(source, **kwargs)
    return items, dict(status, duration_ms=round((time.monotonic() - started) * 1000))


def refresh_sources(store, only=None, *, source_ids=None, due_only=False, maximum=None, include_archive=True, per_host=6, prune=True):
    state = store.source_state(include_archive=False)
    now = datetime.now(UTC).timestamp()
    active = refresh_plan(state, only=only, source_ids=source_ids, due_only=due_only, maximum=maximum, now=now,
                          per_host=per_host)
    validators = store.current_feed_validators() if any(feed.integration == "rss" for feed in active) else {}
    with ThreadPoolExecutor(max_workers=FEED_WORKERS) as pool:
        futures = {}
        for source in active:
            saved = validators.get(source.id, {})
            if source.integration == "publisher-metadata":
                future = pool.submit(timed_read, source, known_urls=store.source_article_urls(source.id))
            elif source.integration == "rss":
                # A targeted owner refresh requests a complete snapshot for recovery.
                cached = saved if only is None and saved.get("feed_url") == source.url else {}
                future = pool.submit(timed_read, source, validators=cached)
            else:
                future = pool.submit(timed_read, source)
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
                         validators=status.get("validators"), unchanged=status.get("unchanged", False),
                         retry_after=status.get("retry_after", 0),
                         duration_ms=status.get("duration_ms"),
                         diagnostics=({"observed": status["observed_entries"], "rejected": status["rejected_entries"]}
                             if "observed_entries" in status else None))
    if prune and only is None and source_ids is None:
        store.prune()
    return source_catalog(store, include_archive=include_archive)


def source_catalog(store=None, *, include_archive=True):
    states = store.source_state(include_archive=include_archive) if store else {}
    now = datetime.now(UTC)
    morning = morning_refresh_at(now)
    cutoff = (now - FRESH_FOR).isoformat()
    result = []
    for s in DEFAULT_SOURCES:
        state = states.get(s.id, {})
        feed = {**s.public(), "region_id": region_id(s.region), "enabled": state.get("enabled", s.enabled),
                "available": state.get("available"), "last_success": timestamp(state.get("last_success")),
                "checked_at": timestamp(state.get("checked")), "count": state.get("count", 0)}
        feed["latest_published_at"] = state.get("latest_published_at")
        feed["retained_count"] = state.get("retained_count", 0)
        mode = refresh_mode()
        feed.update(refresh_policy=mode, refresh_minutes=1440 if mode == "daily" else s.poll_minutes)
        retry = state.get("retry_at") or 0
        if mode == "daily":
            next_check = morning
            if (state.get("checked") or 0) >= morning.timestamp():
                next_check += timedelta(days=1)
            if retry > next_check.timestamp():
                retry_time = datetime.fromtimestamp(retry, UTC)
                next_check = morning_refresh_at(retry_time)
                if next_check < retry_time:
                    next_check += timedelta(days=1)
        else:
            due = (state.get("checked") or 0) + s.poll_minutes * 60
            next_check = datetime.fromtimestamp(max(now.timestamp(), due, retry), UTC)
        feed["next_check_at"] = next_check.isoformat()
        latest = feed["latest_published_at"]
        feed["content_status"] = ("no_retained_content" if not latest else
            "quiet" if latest < (now - timedelta(days=30)).isoformat() else "recent")
        if state.get("error"):
            feed["error"] = state["error"]
        if feed["enabled"] and (state.get("retry_at") or 0) > now.timestamp():
            feed["retry_at"] = timestamp(state["retry_at"])
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
    if feed.get("refresh_policy") == "daily":
        adjusted_now = datetime.fromisoformat(cutoff) + FRESH_FOR - DAILY_REFRESH_GRACE
        deadline = morning_refresh_at(adjusted_now)
        if deadline > adjusted_now:
            deadline -= timedelta(days=1)
    else:
        tolerance = max(45, feed.get("refresh_minutes", 5) * 2)
        deadline = datetime.fromisoformat(cutoff) - timedelta(minutes=tolerance - 45)
    return "stale" if datetime.fromisoformat(feed["last_success"]) < deadline else "fresh"


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
