"""Discover metadata from reviewed publisher sections when their feeds are shallow.

Reads robots rules first and follows at most eight same-host, allowlisted article
paths. Only JSON-LD headline/date and a short public metadata description are used.
"""
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from app.article_metadata import metadata_for
from app.sanitation import sanitize_text


def article_metadata(body, url, source):
    soup = BeautifulSoup(body, "html.parser", from_encoding="utf-8")
    candidates = []
    for script in soup.select('script[type="application/ld+json"]')[:12]:
        raw = script.string or ""
        if len(raw) > 100000:
            continue
        try:
            # Some publishers leave literal newlines inside articleBody strings.
            # JSON's permissive string mode handles these without executing code.
            data = json.loads(raw, strict=False)
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for item in nodes:
            if isinstance(item, dict):
                candidates.extend(item.get("@graph", [item]))
    title_meta = soup.select_one('meta[property="og:title"]')
    date_meta = soup.select_one('meta[property="article:published_time"], meta[property="og:article:published_time"]')
    if title_meta and date_meta:
        candidates.append({"@type": "Article", "headline": title_meta.get("content"),
                           "datePublished": date_meta.get("content")})
    for data in candidates:
        if not isinstance(data, dict):
            continue
        types = data.get("@type", [])
        types = [types] if isinstance(types, str) else types
        if not isinstance(types, list) or not any(t in ("NewsArticle", "Article", "ReportageNewsArticle", "BlogPosting") for t in types):
            continue
        title = sanitize_text(data.get("headline"), limit=500)
        try:
            published = datetime.fromisoformat(str(data.get("datePublished", "")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        now = datetime.now(UTC)
        if not title or published.utcoffset() is None or not now - timedelta(days=90) <= published <= now + timedelta(days=1):
            continue
        desc = soup.select_one('meta[name="description"]')
        description = sanitize_text(data.get("description") or (desc.get("content") if desc else ""), limit=400)
        author = data.get("author", [])
        author = [author] if isinstance(author, dict) else author
        names = [item.get("name", "") for item in author[:4] if isinstance(item, dict)] if isinstance(author, list) else []
        return {"id": hashlib.sha256(url.encode()).hexdigest()[:20], "url": url, "title": title,
            "description": description, "published_at": published.astimezone(UTC).isoformat(),
            "source_id": source.id, "source": source.group, "publisher": source.label,
            "kind": source.kind, "category": "News", **metadata_for({"author": ", ".join(names)})}
    return None


def read_listing(source, fetch, *, known_urls=()):
    from app.news import canonical_url, article_in_scope
    origin = urlsplit(source.url)
    robots_url = f"https://{origin.netloc}/robots.txt"
    rules = RobotFileParser()
    rules.parse(fetch(robots_url).decode("utf-8", errors="replace").splitlines())
    if not rules.can_fetch("InformaAI", source.url):
        raise ValueError("Section disallowed by publisher")
    delay = rules.crawl_delay("InformaAI") or 0
    if delay > 5:
        raise ValueError("Publisher crawl delay requires a dedicated connector")
    listing = BeautifulSoup(fetch(source.url), "html.parser", from_encoding="utf-8")
    links = []
    for anchor in listing.select("a[href]"):
        try:
            url = canonical_url(urljoin(source.url, anchor["href"]))
        except ValueError:
            continue
        parsed = urlsplit(url)
        if (parsed.netloc != origin.netloc or not parsed.path.startswith(source.article_paths)
                or url in links or not rules.can_fetch("InformaAI", url)):
            continue
        links.append(url)
        if len(links) == 48:
            break
    if not links:
        raise ValueError("No reviewed article links")
    items, failures, attempted = [], 0, 0
    started = time.monotonic()
    for url in links:
        if url in known_urls:
            continue
        if attempted >= 8 or time.monotonic() - started >= 24:
            break
        attempted += 1
        try:
            if delay:
                time.sleep(delay)
            if article := article_metadata(fetch(url), url, source):
                if article_in_scope(source, urlsplit(url).path, article["title"], []):
                    items.append(article)
            else:
                failures += 1
        except Exception:
            failures += 1
    available = bool(items) or failures == 0
    return items, dict(source.public(), available=available, count=len(items), observed_entries=len(links),
        rejected_entries=failures, **({"error": "metadata_incomplete"} if failures else {}))
