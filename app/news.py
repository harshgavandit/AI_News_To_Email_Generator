"""Fetch only reviewed RSS/Atom URLs, with bounded downloads and per-feed snapshots."""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

from app.sources import DEFAULT_SOURCES, Source
from app.sanitation import sanitize_text

# Compatibility for the original read_feed helper and tests.
ALLOWED_DOMAINS = {s.group: set(s.hosts) for s in DEFAULT_SOURCES}
_cache = {}
_lock = threading.Lock()
_refreshed = 0
MAX_BYTES = 5_000_000
TRACKERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (443, None):
        raise ValueError("Invalid article link")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not k.lower().startswith("utm_") and k.lower() not in TRACKERS))
    return urlunsplit(("https", parts.hostname.lower(), parts.path.rstrip("/") or "/", query, ""))


def plain_text(value):
    return sanitize_text(value)


def fetch_bytes(url):
    # Pin feed host to the reviewed registry. Do not follow redirects to other destinations.
    deadline = time.monotonic() + 12
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AIBrief/1.0; +https://github.com/harshgavandit/AI_News_To_Email_Generator)"}
    with httpx.Client(timeout=httpx.Timeout(8, connect=4), follow_redirects=False) as client:
        for _ in range(3):
            with client.stream("GET", url, headers=headers) as response:
                if response.is_redirect:
                    target = str(response.next_request.url)
                    if urlsplit(target).netloc != urlsplit(url).netloc or urlsplit(target).scheme != "https":
                        raise ValueError("Unexpected feed redirect")
                    url = target
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES or time.monotonic() > deadline:
                        raise ValueError("Feed download limit exceeded")
                return bytes(body)
    raise ValueError("Too many feed redirects")


def read_feed(task):
    if isinstance(task, Source):
        s = task
    else:
        group, label, url = task
        s = Source(group, group, label, "news", url, tuple(ALLOWED_DOMAINS[group]))
    status = dict(s.public(), available=False, count=0)
    try:
        if isinstance(task, Source):
            content = fetch_bytes(s.url)
        else:
            # Legacy callable; no HTTP route accepts this tuple from the public.
            with httpx.Client(timeout=12, follow_redirects=False) as client:
                response = client.get(s.url)
                response.raise_for_status()
                content = response.content
        parsed = feedparser.parse(content)
        if not parsed.version:
            return [], dict(status, error="invalid_feed")
        articles = {}
        now = datetime.now(timezone.utc)
        for entry in parsed.entries[:200]:
            try:
                # HN links to arbitrary external sites; retain the reviewed discussion URL.
                url = canonical_url(entry.get("comments", "") if s.id == "hacker-news" else entry.get("link", ""))
                host = urlsplit(url).hostname.removeprefix("www.")
                if host not in {d.removeprefix("www.") for d in s.hosts} or "/shorts/" in url:
                    continue
                date = entry.get("published_parsed") or entry.get("updated_parsed")
                if not date:
                    continue
                published = datetime(*date[:6], tzinfo=timezone.utc)
                if published > now + timedelta(days=1):
                    continue
                title = plain_text(entry.get("title", ""))[:500]
                if not title:
                    continue
                media = entry.get("media_description") or ""
                desc = plain_text(media or entry.get("summary") or entry.get("description") or "")
                tags = entry.get("tags") or [{}]
                articles[url] = {
                    "id": hashlib.sha256(url.encode()).hexdigest()[:20], "title": title,
                    "description": desc, "url": url, "source": s.group, "source_id": s.id,
                    "publisher": s.label, "published_at": published.isoformat(), "kind": s.kind,
                    "category": plain_text(tags[0].get("term", "News"))[:100],
                }
            except (ValueError, TypeError, OverflowError):
                continue
        if parsed.entries and not articles:
            return [], dict(status, error="no_eligible_entries")
        return list(articles.values()), dict(status, available=True, count=len(articles))
    except (httpx.HTTPError, ValueError, OSError):
        return [], dict(status, error="fetch_failed")


def collect_news():
    """Development and no-database fallback. Production ingestion uses refresh_sources."""
    global _refreshed
    with _lock:
        if not _cache or time.monotonic() - _refreshed >= 300:
            enabled = [s for s in DEFAULT_SOURCES if s.enabled]
            with ThreadPoolExecutor(max_workers=10) as pool:
                for s, (articles, status) in zip(enabled, pool.map(read_feed, enabled)):
                    checked_at = datetime.now(timezone.utc).isoformat()
                    previous_articles, previous_status = _cache.get(s.id, ([], {}))
                    status["checked_at"] = checked_at
                    status["last_success"] = checked_at if status["available"] else previous_status.get("last_success")
                    if not status["available"]:
                        articles = previous_articles
                        status["count"] = len(articles)
                    _cache[s.id] = (articles, status)
            _refreshed = time.monotonic()
        unique = {a["url"]: a for articles, _ in _cache.values() for a in articles}
        return {"articles": sorted(unique.values(), key=lambda a: (a["published_at"], a["id"]), reverse=True),
                "sources": [status for _, status in _cache.values()],
                "fetched_at": max((status["checked_at"] for _, status in _cache.values()), default=None)}
