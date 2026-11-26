"""Scheduled and admin-triggered refresh; browsing never waits on it with a store."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta, timezone
from collections import Counter
import logging
import os
import threading
import time
from urllib.parse import urlsplit

from app.coverage import region_id
from app.news import FEED_WORKERS, read_feed
from app.sources import DEFAULT_SOURCES

INDIA_TIME = timezone(timedelta(hours=5, minutes=30))
SWEEP_INTERVAL = timedelta(hours=12)
SWEEP_WINDOW = timedelta(minutes=45)
# GitHub runs full sweeps and Vercel checks its small publisher set inside SWEEP_WINDOW.
# GitHub can start hours late, so a continuation can finish the same sweep until an
# hour before the next one begins.
SWEEP_CATCHUP = timedelta(hours=11)
HOST_WORKERS = 2
# Light checks at 02:00 and 14:00 IST cover the busiest newsrooms, advisories and status
# pages between full sweeps. GitHub starts them, and its schedule can run hours late, so the
# window stays open until 30 minutes before the next full sweep.
PRIORITY_WINDOW = timedelta(hours=5, minutes=30)
PRIORITY_COVERAGE = frozenset({"reporting", "advisory", "status"})
PRIORITY_POLL_MINUTES = 15
# Hosts that serve many reviewed feeds from robust infrastructure. GitHub release
# Atom feeds (~80 sources) would otherwise drain two at a time and miss the sweep.
HOST_LIMITS = {"github.com": 6}


# Publishers that refuse GitHub Actions' network (HTTP 403 from Substack, Cloudflare or
# Akamai rules for cloud ranges) but serve Vercel. GitHub runs every other feed; Vercel's
# 08:00/20:00 IST schedule fetches only these few itself, which costs seconds of CPU.
# Found in GitHub sweep run #77 on 23 November 2026.
VERCEL_FETCHED = frozenset({
    "import-ai", "the-chip-letter", "thezvi",            # Substack
    "indian-express-tech", "gizmodo-tech", "tech-eu", "the-bridge-jp",
    "moneycontrol-tech", "moneycontrol-news-index",
})
SWEEP_RUNNER_ENV = "INFORMA_SWEEP_RUNNER"


def runner_excluded(environ=None):
    """Sources this process must leave to another runner (none outside GitHub Actions)."""
    environ = os.environ if environ is None else environ
    return VERCEL_FETCHED if environ.get(SWEEP_RUNNER_ENV) == "github" else frozenset()


def host_limit(host):
    return HOST_LIMITS.get(host, HOST_WORKERS)


# Network blips and publisher 5xx responses often clear within seconds. A scheduled
# sweep retries these once, after the rest of its queue, instead of waiting 12 hours.
TRANSIENT_ERRORS = frozenset({"fetch_timeout", "fetch_failed", "connection_failed", "upstream_unavailable"})

HOST_GATES = {}
_HOST_GATES_LOCK = threading.Lock()


def host_gate(host):
    with _HOST_GATES_LOCK:
        if host not in HOST_GATES:
            HOST_GATES[host] = threading.Semaphore(host_limit(host))
        return HOST_GATES[host]
logger = logging.getLogger(__name__)


def latest_sweep(now):
    local = now.astimezone(INDIA_TIME)
    scheduled = local.replace(hour=20 if local.hour >= 20 else 8, minute=0, second=0, microsecond=0).astimezone(UTC)
    return scheduled if now >= scheduled else scheduled - SWEEP_INTERVAL


def latest_priority_check(now):
    local = now.astimezone(INDIA_TIME)
    scheduled = local.replace(hour=14 if local.hour >= 14 else 2, minute=0, second=0, microsecond=0).astimezone(UTC)
    return scheduled if now >= scheduled else scheduled - SWEEP_INTERVAL


def priority_source(source):
    """High-volume newsrooms, security advisories and status pages that publish around the clock."""
    return (source.coverage in PRIORITY_COVERAGE and source.kind != "video"
            and source.poll_minutes <= PRIORITY_POLL_MINUTES)


PRIORITY_SOURCE_IDS = frozenset(source.id for source in DEFAULT_SOURCES if priority_source(source))


def access_denied(state, now=None):
    """A publisher that refuses us access (HTTP 401/403) is taken out of fetching.

    A feed that has never worked leaves on its first refusal. One that has worked keeps
    TEMPORARY_GRACE to recover from a passing block. Rate limits (HTTP 429), timeouts and
    publisher outages are not refusals: those feeds stay and are retried.
    """
    if state.get("available") is not False or state.get("error") != "access_denied":
        return False
    last = state.get("last_success")
    return not last or (now or time.time()) - last >= TEMPORARY_GRACE.total_seconds()


def source_enabled(source, state):
    return source.enabled and state.get("enabled", True) and not access_denied(state)


def sweep_plan(state, scheduled, now, *, attempts=(), source_ids=None, host_backoffs=None):
    """One scheduled check per enabled source in each 08:00 and 20:00 IST sweep."""
    host_backoffs = host_backoffs or {}
    pending = {source.id: max(state.get(source.id, {}).get("retry_at") or 0, host_backoffs.get(feed_host(source), 0))
               for source in DEFAULT_SOURCES
               if source_enabled(source, state.get(source.id, {}))
               and source.id not in attempts
               and (source_ids is None or source.id in source_ids)
               and (state.get(source.id, {}).get("checked") or 0) < scheduled.timestamp()}
    deferred = {ident: retry for ident, retry in pending.items() if retry > now.timestamp()}
    return pending.keys() - deferred.keys(), deferred


def refresh_plan(state, *, only=None, source_ids=None, maximum=None, now=None, per_host=12):
    now = now or datetime.now(UTC).timestamp()
    candidates = [source for source in DEFAULT_SOURCES if (only is None or source.id == only)
        and source_enabled(source, state.get(source.id, {}))
        and (state.get(source.id, {}).get("retry_at") or 0) <= now
        and (source_ids is None or source.id in source_ids)]
    # Use legacy cadence as a priority weight within each sweep.
    candidates.sort(key=lambda source: (-(now - (state.get(source.id, {}).get("checked") or 0)) /
                                       (source.poll_minutes * 60), source.id))
    if maximum is None:
        return candidates
    # Reserve a quarter of each batch for oldest checks to prevent starvation.
    oldest = sorted(candidates, key=lambda source: (state.get(source.id, {}).get("checked") or 0, source.id))
    ordered = [*oldest[:max(1, maximum // 4)], *candidates]
    selected, hosts, seen = [], Counter(), set()
    for source in ordered:
        if source.id in seen:
            continue
        host = feed_host(source)
        if hosts[host] >= per_host:
            continue
        selected.append(source)
        seen.add(source.id)
        hosts[host] += 1
        if len(selected) == maximum:
            break
    return selected


def feed_host(source):
    return urlsplit(source.url).hostname.removeprefix("www.")


def timed_read(source, *, claim=None, **kwargs):
    started = time.monotonic()
    with host_gate(feed_host(source)):
        if claim is not None and not claim(source.id):
            return None
        try:
            items, status = read_feed(source, **kwargs)
        except Exception as error:
            # Exception text can contain signed URLs. Retain only its type.
            logger.warning("publisher_parser_error source_id=%s error_type=%s", source.id, type(error).__name__)
            items, status = [], {"available": False, "error": "parser_failed"}
    return items, dict(status, duration_ms=round((time.monotonic() - started) * 1000))


def next_source(pending, running, limit=host_limit):
    """Pick the next eligible source, starting with the host that needs longest to drain.

    Priority order is kept within a host. Starting the deepest queues first keeps a
    host with many feeds from becoming the tail that runs past the sweep deadline.
    """
    queued = Counter(host for _, host in pending)
    best, best_drain, seen = None, -1.0, set()
    for index, (_, host) in enumerate(pending):
        if host in seen:
            continue  # Only each host's highest-priority source is a candidate.
        seen.add(host)
        allowed = limit(host)
        if running[host] >= allowed:
            continue
        drain = queued[host] / allowed
        if drain > best_drain:
            best, best_drain = index, drain
    return best


def refresh_sources(store, only=None, *, source_ids=None, maximum=None, scheduled=None, deadline=None,
                    window=SWEEP_WINDOW):
    state = store.source_state(include_archive=False)
    now = datetime.now(UTC).timestamp()
    active = refresh_plan(state, only=only, source_ids=source_ids, maximum=maximum, now=now)
    validators = store.current_feed_validators() if any(feed.integration == "rss" for feed in active) else {}
    host_backoffs = store.feed_host_backoffs(now) if scheduled is not None else {}

    def claim(source_id, retry=False):
        slot = scheduled.isoformat(timespec="minutes") + (":retry" if retry else "")
        return (scheduled <= datetime.now(UTC) < scheduled + window
                and (deadline is None or time.monotonic() < deadline)
                and store.claim_feed_check(source_id, slot))

    # A host earns its larger allowance only after a healthy response in this run, so
    # a rate-limited publisher still sees at most HOST_WORKERS requests before backoff.
    proven = set()

    def effective_limit(host):
        return host_limit(host) if host in proven else min(HOST_WORKERS, host_limit(host))

    with ThreadPoolExecutor(max_workers=FEED_WORKERS) as pool:
        futures, hosts = {}, Counter()
        pending = [(source, feed_host(source)) for source in active]
        retried = set()
        while pending or futures:
            # Keep a congested publisher from tying up all workers for unrelated hosts.
            if deadline is not None and time.monotonic() >= deadline:
                pending.clear()
            while pending and len(futures) < FEED_WORKERS:
                index = next_source(pending, hosts, effective_limit)
                if index is None:
                    break
                source, host = pending.pop(index)
                if host_backoffs.get(host, 0) > time.time():
                    continue
                saved = validators.get(source.id, {})
                retry = source.id in retried
                options = {"claim": (lambda ident: claim(ident, retry=True)) if retry else claim} if scheduled is not None else {}
                if source.integration == "publisher-metadata":
                    options["known_urls"] = store.source_article_urls(source.id)
                elif source.integration == "rss":
                    options["validators"] = saved if only is None and saved.get("feed_url") == source.url else {}
                futures[pool.submit(timed_read, source, **options)] = (source, host)
                hosts[host] += 1
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                source, host = futures.pop(future)
                hosts[host] -= 1
                result = future.result()
                if result is not None:
                    record_check(store, source, *result)
                    status = result[1]
                    if (scheduled is not None and source.id not in retried and status.get("available") is False
                            and status.get("error") in TRANSIENT_ERRORS):
                        retried.add(source.id)
                        pending.append((source, host))
                    limited = status.get("rate_limit_host")
                    if status.get("available") and not limited:
                        proven.add(host)
                    if scheduled is not None and limited and len(limited) <= 140:
                        until = time.time() + max(900, status.get("retry_after", 0))
                        if until > host_backoffs.get(limited, 0):
                            store.defer_feed_host(limited, until)
                            host_backoffs[limited] = until

    if scheduled is not None:
        return
    if only is None and source_ids is None:
        store.prune()
    return source_catalog(store)


def record_check(store, source, items, status):
    if not status["available"] or status.get("retry_after") or status.get("error") == "rate_limited":
        logger.warning("publisher_check_%s source_id=%s publisher=%r reason=%s duration_ms=%s retry_after_seconds=%s",
                       "partial" if status["available"] else "failed", source.id, source.label, status.get("error") or "unknown",
                       status.get("duration_ms"), status.get("retry_after", 0))
    store.ingest(source.id, items, status["available"], status.get("error"),
                 feed_url=source.url if source.integration == "rss" else None,
                 validators=status.get("validators"), unchanged=status.get("unchanged", False),
                 retry_after=status.get("retry_after", 0),
                 duration_ms=status.get("duration_ms"),
                 diagnostics=({"observed": status["observed_entries"], "rejected": status["rejected_entries"]}
                     if "observed_entries" in status else None))


def source_catalog(store=None, *, include_archive=True):
    states = store.source_state(include_archive=include_archive) if store else {}
    now = datetime.now(UTC)
    scheduled = latest_sweep(now)
    attempts = store.feed_attempts(scheduled.isoformat(timespec="minutes")) if store else set()
    host_backoffs = store.feed_host_backoffs(now.timestamp()) if store else {}
    result = []
    for s in DEFAULT_SOURCES:
        state = states.get(s.id, {})
        feed = {**s.public(), "region_id": region_id(s.region), "enabled": source_enabled(s, state),
                "available": state.get("available"), "last_success": timestamp(state.get("last_success")),
                "checked_at": timestamp(state.get("checked")), "count": state.get("count", 0)}
        feed["latest_published_at"] = state.get("latest_published_at")
        feed["retained_count"] = state.get("retained_count", 0)
        priority = s.id in PRIORITY_SOURCE_IDS
        feed.update(refresh_policy="four_times_daily" if priority else "twice_daily",
                    refresh_minutes=360 if priority else 720)
        retry = max(state.get("retry_at") or 0, host_backoffs.get(feed_host(s), 0))
        next_check = scheduled
        if (now >= scheduled + SWEEP_WINDOW or s.id in attempts
                or (state.get("checked") or 0) >= scheduled.timestamp()):
            next_check += SWEEP_INTERVAL
        if retry > next_check.timestamp():
            retry_time = datetime.fromtimestamp(retry, UTC)
            next_check = latest_sweep(retry_time)
            if next_check < retry_time:
                next_check += SWEEP_INTERVAL
        if priority:
            light = latest_priority_check(now)
            if now >= light + PRIORITY_WINDOW or (state.get("checked") or 0) >= light.timestamp():
                light += SWEEP_INTERVAL
            if retry <= light.timestamp() < next_check.timestamp():
                next_check = light
        feed["next_check_at"] = next_check.isoformat() if feed["enabled"] else None
        latest = feed["latest_published_at"]
        feed["content_status"] = ("no_retained_content" if not latest else
            "quiet" if latest < (now - timedelta(days=30)).isoformat() else "recent")
        if state.get("error"):
            feed["error"] = state["error"]
        if s.enabled and access_denied(state, now.timestamp()):
            feed["pause_reason"] = "The publisher denies automated access, so this feed is no longer fetched."
        if feed["enabled"] and retry > now.timestamp():
            feed["retry_at"] = timestamp(retry)
        feed["freshness"] = (source_freshness(feed, now) if feed["enabled"] else "paused")
        feed["health"] = source_health(feed, now)
        result.append(feed)
    return result


# Errors that mean the feed address itself no longer works, as opposed to a busy or slow server.
LASTING_ERRORS = frozenset({"feed_not_found", "access_denied", "dns_failed", "tls_failed", "parser_failed"})
TEMPORARY_GRACE = timedelta(days=14)
BROKEN_AFTER = timedelta(days=30)


def source_health(feed, now):
    """Publishing, quiet, temporarily unavailable or broken. Silence alone is never a failure."""
    if not feed["enabled"]:
        return "paused"
    if feed["available"] is None and not feed.get("last_success"):
        return "pending"
    if feed["available"] is False:
        last = datetime.fromisoformat(feed["last_success"]) if feed.get("last_success") else None
        if last and now - last < TEMPORARY_GRACE:
            return "temporarily_unavailable"
        if (last and now - last >= BROKEN_AFTER) or (feed.get("error") in LASTING_ERRORS
                                                     and (last is None or now - last >= TEMPORARY_GRACE)):
            return "broken"
        return "temporarily_unavailable"
    return "active" if feed["content_status"] == "recent" else "quiet"


def timestamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value else None


def source_freshness(feed, now):
    if feed["available"] is False:
        return "failed"
    if not feed.get("last_success"):
        return "pending"
    deadline = latest_sweep(now - SWEEP_WINDOW)
    return "stale" if datetime.fromisoformat(feed["last_success"]) < deadline else "fresh"


def selected_feeds(catalog, *, source="all", publisher="", kind="all", region="", coverage="", language=""):
    return [feed for feed in catalog if feed["enabled"] and (source == "all" or source in (feed["id"], feed["source"]))
            and (not publisher or feed["id"] == publisher) and (kind == "all" or feed["kind"] == kind)
            and (not region or region_id(feed.get("region", "Global")) == region)
            and (not coverage or feed.get("coverage") == coverage)
            and (not language or feed.get("language") == language)]


def feed_freshness(catalog, **filters):
    active = selected_feeds(catalog, **filters)
    now = datetime.now(UTC)
    counts = dict(enabled=len(active), fresh=0, stale=0, failed=0, pending=0)
    for feed in active:
        counts[source_freshness(feed, now)] += 1

    if counts["fresh"]:
        status = "fresh" if counts["fresh"] == len(active) else "degraded"
    elif counts["failed"] or counts["stale"]:
        status = "stale"
    else:
        status = "pending"
    return {"status": status, "counts": counts,
            "checked_at": max((s.get("checked_at") or "" for s in active), default="") or None,
            "last_success": max((s.get("last_success") or "" for s in active), default="") or None,
            "next_full_sweep_at": (latest_sweep(now) + SWEEP_INTERVAL).isoformat() if active else None}


def ingestion_health(store, catalog=None):
    """Expose scheduler progress and source-specific deadlines without masking a backlog."""
    catalog = catalog if catalog is not None else source_catalog(store, include_archive=False)
    now = datetime.now(UTC)
    state = store.source_state(include_archive=False)
    active = [feed for feed in catalog if feed["enabled"]]
    scheduled = latest_sweep(now)
    attempts = store.feed_attempts(scheduled.isoformat(timespec="minutes"))
    due, deferred = sweep_plan(state, scheduled, now, attempts=attempts, host_backoffs=store.feed_host_backoffs(now.timestamp()))
    unconfirmed = {feed["id"] for feed in active if feed["id"] in attempts
                   and (state.get(feed["id"], {}).get("checked") or 0) < scheduled.timestamp()}
    last_check = max((state.get(feed["id"], {}).get("checked") or 0 for feed in active), default=0)
    expected = latest_sweep(now - SWEEP_WINDOW).timestamp()
    lag = sorted(max(0, expected - state[feed["id"]]["checked"])
                 for feed in active if state.get(feed["id"], {}).get("checked"))
    priority = {source.id for source in DEFAULT_SOURCES if source.poll_minutes <= 15}
    critical = [feed for feed in active if feed["id"] in priority]
    overdue_critical = [feed for feed in critical if
        (state.get(feed["id"], {}).get("checked") or 0) < expected]
    closed = now >= scheduled + SWEEP_WINDOW
    return {"status": "stalled" if active and last_check < expected else
                      "backlogged" if closed and (due or unconfirmed) else "running",
            "last_check_at": timestamp(last_check), "seconds_since_check": round(now.timestamp() - last_check) if last_check else None,
            "due_sources": len(due), "deferred_sources": len(deferred), "unconfirmed_sources": len(unconfirmed),
            "pending_sources": sum(not state.get(feed["id"], {}).get("checked") for feed in active),
            "priority_sources": len(critical), "priority_sources_overdue": len(overdue_critical),
            "p95_overdue_seconds": round(lag[min(len(lag) - 1, int(len(lag) * .95))]) if lag else 0,
            "notice": ("Every publisher is checked at 08:00 and 20:00 IST. A sweep starts in a 45-minute window and "
                       "any feeds it could not reach are finished later in the same cycle. The busiest newsrooms, "
                       "advisories and status pages are also checked at 02:00 and 14:00 IST.")}
