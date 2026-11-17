"""Fetch only reviewed RSS/Atom URLs, with bounded downloads and per-feed snapshots."""
import asyncio
import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.sources import DEFAULT_SOURCES, Source
from app.sanitation import sanitize_story_excerpt, sanitize_text
from app.article_metadata import metadata_for, extract_technical_terms
from app.community import GENERAL_DEV_FEEDS, dev_article_in_scope

# Compatibility for the original read_feed helper and tests.
ALLOWED_DOMAINS = {s.group: set(s.hosts) for s in DEFAULT_SOURCES}
_cache = {}
_lock = threading.Lock()
_refreshed = 0
MAX_BYTES = 5_000_000
FEED_WORKERS = 14
TRACKERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "wt_mc", ".tsrc", "__source", "shem"}
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
BARE_VERSION = re.compile(r"v?\d+\.\d+\.\d+(?:[-+][\w.+-]+)?", re.ASCII)
ETAG = re.compile(r'(?:W/)?"[\x21\x23-\x7e]{0,480}"')


@dataclass(frozen=True)
class FeedResponse:
    body: bytes | None
    url: str
    etag: str | None = None
    last_modified: str | None = None


def feed_validator_headers(etag, last_modified):
    headers = {}
    if isinstance(etag, str) and ETAG.fullmatch(etag):
        headers["If-None-Match"] = etag
    if (isinstance(last_modified, str) and 1 <= len(last_modified) <= 80
            and all(32 <= ord(char) < 127 for char in last_modified)):
        headers["If-Modified-Since"] = last_modified
    return headers


def feed_failure(status_code):
    if status_code == 429:
        return "rate_limited"
    if status_code in (401, 403):
        return "access_denied"
    if status_code >= 500:
        return "upstream_unavailable"
    return "fetch_failed"


def http_failure(error):
    response = error.response
    status = {"error": feed_failure(response.status_code)}
    if response.status_code in (429, 503):
        value = response.headers.get("Retry-After", "").strip()
        try:
            delay = int(value) if value.isascii() and value.isdecimal() else (
                parsedate_to_datetime(value).timestamp() - time.time())
            status["retry_after"] = max(0, min(86400, delay))
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    return status


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
    return asyncio.run(fetch_with_deadline(url)).body


async def fetch_with_deadline(url, validators=None):
    # The deadline covers DNS, connection, redirects and the response body.
    headers = {"User-Agent": "InformaAI/1.1 (+https://github.com/harshgavandit/AI_News_To_Email_Generator)"}
    async with asyncio.timeout(10):
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=6), follow_redirects=False, trust_env=False) as client:
            for _ in range(3):
                conditional = (feed_validator_headers(validators.get("etag"), validators.get("last_modified"))
                               if validators and validators.get("resource_url") == url else {})
                async with client.stream("GET", url, headers={**headers, **conditional}) as response:
                    if response.status_code == 304 and conditional:
                        return FeedResponse(None, url)
                    if response.has_redirect_location:
                        target = str(response.next_request.url)
                        destination, origin = urlsplit(target), urlsplit(url)
                        if (destination.scheme != "https" or destination.username or destination.password
                                or destination.port not in (None, 443)
                                or (destination.hostname or "").removeprefix("www.") != (origin.hostname or "").removeprefix("www.")):
                            raise ValueError("Unexpected feed redirect")
                        url = target
                        continue
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(65536):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError("Feed download limit exceeded")
                    fingerprint = feed_validator_headers(response.headers.get("etag"), response.headers.get("last-modified"))
                    return FeedResponse(bytes(body), url, fingerprint.get("If-None-Match"), fingerprint.get("If-Modified-Since"))
    raise ValueError("Too many feed redirects")


def read_feed(task, *, validators=None, known_urls=()):
    if isinstance(task, Source) and task.integration == "crossref-api":
        try:
            from app.scholarly import read_crossref
            return read_crossref(task, fetch_bytes)
        except httpx.HTTPStatusError as error:
            return [], {**task.public(), "available": False, "count": 0, **http_failure(error)}
        except Exception:
            return [], dict(task.public(), available=False, count=0, error="metadata_unavailable")
    if isinstance(task, Source) and task.integration == "publisher-metadata":
        try:
            from app.publisher_listing import read_listing
            return read_listing(task, fetch_bytes, known_urls=known_urls)
        except httpx.HTTPStatusError as error:
            return [], {**task.public(), "available": False, "count": 0, **http_failure(error)}
        except Exception:
            return [], dict(task.public(), available=False, count=0, error="metadata_unavailable")
    if isinstance(task, Source) and task.integration == "news-sitemap":
        try:
            from app.news_sitemap import read_news_sitemap
            return read_news_sitemap(task, fetch_bytes)
        except httpx.HTTPStatusError as error:
            return [], {**task.public(), "available": False, "count": 0, **http_failure(error)}
        except Exception:
            return [], dict(task.public(), available=False, count=0, error="sitemap_unavailable")
    if isinstance(task, Source) and task.integration == "hashnode-api":
        from app.hashnode import read_hashnode
        return read_hashnode(task)
    if isinstance(task, Source) and task.integration != "rss":
        from app.community import read_community
        items, status = read_community(task, fetch_bytes)
        if status["available"]:
            return items, status
        fallback = {"hacker-news-api": "https://news.ycombinator.com/rss", "dev-api": "https://dev.to/feed"}.get(task.integration)
        if task.integration == "dev-api" and (status.get("error") == "rate_limited" or status.get("retry_after")):
            return [], status  # DEV's API and RSS endpoint share the same host.
        if fallback:
            items, fallback_status = read_feed(replace(task, url=fallback, integration="rss"))
            if fallback_status["available"]:
                return items, {**fallback_status, **task.public(), "transport": "official-rss-fallback"}
            if task.integration == "dev-api" and (fallback_status.get("retry_after") or
                                                  fallback_status.get("error") == "rate_limited"):
                return [], {**fallback_status, **task.public()}
        return [], status
    if isinstance(task, Source):
        s = task
    else:
        group, label, url = task
        s = Source(group, group, label, "news", url, tuple(ALLOWED_DOMAINS[group]))
    status = dict(s.public(), available=False, count=0)
    try:
        if validators is not None and isinstance(task, Source):
            feed = asyncio.run(fetch_with_deadline(s.url, validators))
            if feed.body is None:
                return [], dict(status, available=True, unchanged=True)
            content = feed.body
            if feed.etag or feed.last_modified:
                status["validators"] = {"resource_url": feed.url, "etag": feed.etag, "last_modified": feed.last_modified}
        elif isinstance(task, Source):
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
                raw_link = entry.get("comments", "") if s.id == "hacker-news" else entry.get("link", "")
                # Older publisher feeds still advertise HTTP permalinks. Upgrade only
                # reviewed hosts; this never fetches an article or relaxes URL validation.
                candidate = urlsplit(raw_link)
                if (candidate.scheme == "http" and candidate.hostname and candidate.hostname.removeprefix("www.") in allowed_hosts
                        and not candidate.username and not candidate.password and candidate.port in (None, 80)):
                    raw_link = urlunsplit(("https", candidate.hostname, candidate.path, candidate.query, ""))
                url = canonical_url(raw_link, medium=medium)
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
                raw_title = entry.get("title", "")
                title = plain_text(raw_title)[:500]
                if not title and s.coverage == "release" and BARE_VERSION.fullmatch(raw_title):
                    title = f"{s.label.removesuffix(' Releases')} {raw_title}"
                if not title:
                    continue
                has_valid_entry = True
                tags = [plain_text(tag.get("term")) for tag in entry.get("tags", ())[:12]]
                if not article_in_scope(s, parts.path, title, tags):
                    continue
                media = entry.get("media_description") or ""
                raw_desc = media or entry.get("summary") or entry.get("description") or ""
                desc = "" if s.id == "hacker-news" else sanitize_story_excerpt(
                    raw_desc, s.group, title, channel=s.label, video_fallback=False)
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
                media_items = entry.get("media_thumbnail") or entry.get("media_content") or []
                image = next((item.get("url", "") for item in media_items if isinstance(item, dict)), "")
                story_record.update(metadata_for({"tags": tags,
                    "technical_terms": extract_technical_terms(raw_desc),
                    "references": [{"url": link.get("href"), "label": link.get_text(" ", strip=True)}
                        for link in BeautifulSoup(raw_desc[:50000], "html.parser").select("a[href]")[:8]],
                    "author_url": s.author_url if not entry.get("author") or entry.get("author") == s.author_name else None,
                    "author": entry.get("author") or s.author_name,
                    "thumbnail_url": image, "original_url": entry.get("link") if s.id == "hacker-news" else None,
                    "discussion_url": url if s.id == "hacker-news" else None}))
                if s.id in GENERAL_DEV_FEEDS and not dev_article_in_scope(story_record):
                    continue
                articles[article_id] = story_record
            except (ValueError, TypeError, OverflowError, AttributeError, IndexError):
                continue
        if parsed.entries and not has_valid_entry:
            return [], dict(status, error="no_eligible_entries")
        return list(articles.values()), dict(status, available=True, count=len(articles),
            observed_entries=len(parsed.entries), rejected_entries=min(200, len(parsed.entries)) - len(articles),
            latest_published_at=max((article["published_at"] for article in articles.values()), default=None))
    except httpx.HTTPStatusError as error:
        return [], {**status, **http_failure(error)}
    except (httpx.HTTPError, ValueError, OSError):
        return [], dict(status, error="fetch_failed")


def safe_read_feed(source):
    try:
        return read_feed(source)
    except Exception:
        return [], dict(source.public(), available=False, count=0, error="parser_failed")


def collect_news(*, force=False):
    """Development and no-database fallback. Production ingestion uses refresh_sources."""
    global _refreshed
    with _lock:
        cache_age = time.monotonic() - _refreshed
        if not _cache or cache_age >= (30 if force else 300):
            now = datetime.now(timezone.utc).isoformat()
            enabled = [s for s in DEFAULT_SOURCES if s.enabled and (
                _cache.get(s.id, ([], {}))[1].get("retry_at") or "") <= now]
            with ThreadPoolExecutor(max_workers=FEED_WORKERS) as pool:
                for s, (articles, status) in zip(enabled, pool.map(safe_read_feed, enabled)):
                    checked = datetime.now(timezone.utc)
                    checked_at = checked.isoformat()
                    previous_articles, previous_status = _cache.get(s.id, ([], {}))
                    status["checked_at"] = checked_at
                    status["last_success"] = checked_at if status["available"] else previous_status.get("last_success")
                    delay = max(status.get("retry_after", 0), 900 if status.get("error") == "rate_limited" else 0)
                    if delay:
                        status["retry_at"] = (checked + timedelta(seconds=delay)).isoformat()
                    if not status["available"]:
                        articles = previous_articles
                        status["count"] = len(articles)
                    _cache[s.id] = (articles, status)
            _refreshed = time.monotonic()
        unique = {}
        for feed_id, (items, _) in _cache.items():
            for article in items:
                ident = article["id"]
                if ident in unique:
                    first = unique[ident]
                    unique[ident] = dict(first, _feed_ids=(*first.get("_feed_ids", ()), feed_id))
                else:
                    unique[ident] = article
        return {"articles": sorted(unique.values(), key=lambda a: (a["published_at"], a["id"]), reverse=True),
                "sources": [status for _, status in _cache.values()],
                "fetched_at": max((status["checked_at"] for _, status in _cache.values()), default=None)}
