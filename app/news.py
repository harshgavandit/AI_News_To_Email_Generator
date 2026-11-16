"""Fetch only reviewed RSS/Atom URLs, with bounded downloads and per-feed snapshots."""
import asyncio
import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

from app.sources import DEFAULT_SOURCES, Source
from app.sanitation import sanitize_story_excerpt, sanitize_text

# Compatibility for the original read_feed helper and tests.
ALLOWED_DOMAINS = {s.group: set(s.hosts) for s in DEFAULT_SOURCES}
_cache = {}
_lock = threading.Lock()
_refreshed = 0
MAX_BYTES = 5_000_000
FEED_WORKERS = 14
TRACKERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "wt_mc", ".tsrc", "__source"}
TECH_SECTION = re.compile(r"\b(?:tech(?:nology|-science)?|artificial intelligence|ai)\b", re.I)
TECH_HEADLINE = re.compile(
    r"\b(?:AI|LLM|NVIDIA|Jensen Huang|ChatGPT|OpenAI|Anthropic|Google|Microsoft|Apple|Meta|Amazon|TikTok|"
    r"SpaceX|Intel|AMD|TSMC|Samsung|LG Electronics|SK Hynix|Huawei|ByteDance|Tencent|Alibaba|"
    r"semiconductors?|chipmakers?|cyber\w*|ransomware|software|data cent(?:er|re)s?|smartphones?|"
    r"robots?|robotics|telecom\w*|blockchain|bitcoin|cloud computing|artificial intelligence|"
    r"autonomous (?:cars?|vehicles?|ships?|vessels?)|(?:electric|electrified) vehicles?)\b", re.I
)
SPONSORED_TITLE = re.compile(
    r"^(?:heise-angebot|anzeige|sponsored content|sponsored post|advertisement|partner content)\s*[:|]", re.I
)
MEDIUM_POST = re.compile(r"https://medium\.com/p/([a-f0-9]{8,16})\Z")


def canonical_url(url, *, medium=False):
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
        raise ValueError("Invalid article link")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password or
            parts.port not in (443, None) or not parts.hostname.isascii() or ":" in parts.hostname):
        raise ValueError("Invalid article link")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True, max_num_fields=64)
                             if not k.lower().startswith("utm_") and k.lower() not in TRACKERS
                             and not (medium and (k.lower() == "sk" or k.lower() == "source" and v.startswith("rss-")))))
    return urlunsplit(("https", parts.hostname.lower(), parts.path.rstrip("/") or "/", query, ""))


def plain_text(value):
    return sanitize_text(value)


def article_in_scope(source, path, title, tags):
    if source.article_paths and not path.startswith(source.article_paths):
        return False
    if path.startswith(source.excluded_paths) or SPONSORED_TITLE.match(title):
        return False
    return not source.tech_only or bool(TECH_HEADLINE.search(title)) or any(
        TECH_SECTION.fullmatch(section) for section in (*tags, *path.split("/"))
    )


def feed_category(tags):
    category = ""
    for tag in dict.fromkeys(tags):
        if not tag:
            continue
        combined = f"{category} | {tag}" if category else tag[:100]
        if len(combined) > 100:
            break
        category = combined
    return category or "News"


def fetch_bytes(url):
    return asyncio.run(fetch_with_deadline(url))


async def fetch_with_deadline(url):
    # The deadline covers DNS, connection, redirects and the response body.
    headers = {"User-Agent": "Mozilla/5.0 (compatible; InformaAI/1.0; +https://github.com/harshgavandit/AI_News_To_Email_Generator)"}
    async with asyncio.timeout(10):
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=6), follow_redirects=False, trust_env=False) as client:
            for _ in range(3):
                async with client.stream("GET", url, headers=headers) as response:
                    if response.is_redirect:
                        target = str(response.next_request.url)
                        if urlsplit(target).netloc != urlsplit(url).netloc or urlsplit(target).scheme != "https":
                            raise ValueError("Unexpected feed redirect")
                        url = target
                        continue
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(65536):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
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
        if len(content) > MAX_BYTES:
            return [], dict(status, error="feed_too_large")
        parsed = feedparser.parse(content, response_headers={"content-location": s.url})
        if not parsed.get("version"):
            return [], dict(status, error="invalid_feed")
        articles = {}
        has_valid_entry = False
        medium = s.group == "medium"
        allowed_hosts = {domain.removeprefix("www.") for domain in s.hosts}
        now = datetime.now(timezone.utc)
        for entry in parsed.entries[:200]:
            try:
                # HN links to arbitrary external sites; retain the reviewed discussion URL.
                url = canonical_url(entry.get("comments", "") if s.id == "hacker-news" else entry.get("link", ""), medium=medium)
                parts = urlsplit(url)
                host = parts.hostname.removeprefix("www.")
                allowed_link = host in allowed_hosts or (medium and host.endswith(".medium.com"))
                if not allowed_link or "/shorts/" in parts.path:
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
                has_valid_entry = True
                tags = [plain_text(tag.get("term")) for tag in entry.get("tags", ())[:12]]
                if not article_in_scope(s, parts.path, title, tags):
                    continue
                media = entry.get("media_description") or ""
                raw_content = ""
                if entry.get("content"):
                    for c in entry.get("content"):
                        if isinstance(c, dict) and c.get("value"):
                            raw_content = c.get("value")
                            break
                raw_desc = media or entry.get("summary") or entry.get("description") or ""
                desc = "" if s.id == "hacker-news" else sanitize_story_excerpt(
                    raw_desc, s.group, title, channel=s.label, video_fallback=False)
                full_body = ""
                if s.id != "hacker-news":
                    cleaned_body = sanitize_text(raw_content or raw_desc, limit=3500)
                    if len(cleaned_body) > len(desc) + 60:
                        full_body = cleaned_body
                post = MEDIUM_POST.fullmatch(entry.get("id", "")) if medium else None
                # Require the permalink and feed GUID to agree before using the shared Medium ID.
                identity = post[0] if post and parts.path.rsplit("/", 1)[-1].split("-")[-1] == post[1] else url
                article_id = hashlib.sha256(identity.encode()).hexdigest()[:20]
                story_record = {
                    "id": article_id, "title": title,
                    "description": desc, "url": url, "source": s.group, "source_id": s.id,
                    "publisher": s.label, "published_at": published.isoformat(), "kind": s.kind,
                    "category": feed_category(tags),
                }
                if full_body:
                    story_record["full_text"] = full_body
                articles[article_id] = story_record
            except (ValueError, TypeError, OverflowError, AttributeError, IndexError):
                continue
        if parsed.entries and not has_valid_entry:
            return [], dict(status, error="no_eligible_entries")
        return list(articles.values()), dict(status, available=True, count=len(articles))
    except (httpx.HTTPError, ValueError, OSError):
        return [], dict(status, error="fetch_failed")


def collect_news(*, force=False):
    """Development and no-database fallback. Production ingestion uses refresh_sources."""
    global _refreshed
    with _lock:
        cache_age = time.monotonic() - _refreshed
        if not _cache or cache_age >= (30 if force else 300):
            enabled = [s for s in DEFAULT_SOURCES if s.enabled]
            with ThreadPoolExecutor(max_workers=FEED_WORKERS) as pool:
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
        unique = {}
        for items, _ in _cache.values():
            for article in items:
                unique.setdefault(article["id"], article)
        return {"articles": sorted(unique.values(), key=lambda a: (a["published_at"], a["id"]), reverse=True),
                "sources": [status for _, status in _cache.values()],
                "fetched_at": max((status["checked_at"] for _, status in _cache.values()), default=None)}
