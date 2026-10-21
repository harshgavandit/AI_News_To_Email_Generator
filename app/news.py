"""Bounded, concurrent RSS collection shared by the web API."""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

FEEDS = {
    "openai": [("OpenAI News", "https://openai.com/news/rss.xml")],
    "anthropic": [
        ("Anthropic News", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml"),
        ("Anthropic Research", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml"),
        ("Anthropic Engineering", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml"),
    ],
    "youtube": [("Matthew Berman", "https://www.youtube.com/feeds/videos.xml?channel_id=UCawZsQWqfGSbCI5yjkdVkTA")],
}
ALLOWED_DOMAINS = {"openai": {"openai.com"}, "anthropic": {"anthropic.com"}, "youtube": {"www.youtube.com", "youtube.com"}}
_cache = None
_lock = threading.Lock()


def plain_text(value: str) -> str:
    return " ".join(BeautifulSoup(value or "", "html.parser").get_text(" ").split())[:4000]


def read_feed(task: tuple) -> tuple[list, dict]:
    source, label, url = task
    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; AIBrief/1.0; +https://github.com/harshgavandit/AI_News_To_Email_Generator)"})
            response.raise_for_status()
        feed = feedparser.parse(response.content[:3_000_000])
        articles = []
        for entry in feed.entries[:80]:
            url = entry.get("link", "")
            parsed = urlparse(url)
            host = (parsed.hostname or "").removeprefix("www.")
            if parsed.scheme != "https" or host not in {d.removeprefix("www.") for d in ALLOWED_DOMAINS[source]}:
                continue
            date = entry.get("published_parsed") or entry.get("updated_parsed")
            if not date or "/shorts/" in url:
                continue
            articles.append({
                "id": hashlib.sha256(url.encode()).hexdigest()[:20],
                "title": plain_text(entry.get("title", "Untitled")),
                "description": plain_text(entry.get("summary", entry.get("description", ""))),
                "url": url, "source": source, "publisher": label,
                "published_at": datetime(*date[:6], tzinfo=timezone.utc).isoformat(),
                "category": plain_text(entry.get("tags", [{}])[0].get("term", "News")),
            })
        return articles, {"source": source, "label": label, "available": bool(articles), "count": len(articles)}
    except (httpx.HTTPError, ValueError, OverflowError):
        return [], {"source": source, "label": label, "available": False, "count": 0}


def collect_news() -> dict:
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < 300:
            return _cache[1]
        tasks = [(source, label, url) for source, feeds in FEEDS.items() for label, url in feeds]
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(read_feed, tasks))
        unique = {a["url"]: a for articles, _ in results for a in articles}
        payload = {
            "articles": sorted(unique.values(), key=lambda a: a["published_at"], reverse=True)[:180],
            "sources": [status for _, status in results],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        # A failed request must not replace a previously good snapshot.
        if not payload["articles"] and _cache:
            stale = dict(_cache[1], stale=True, sources=payload["sources"])
            return stale
        _cache = (time.monotonic(), payload)
        return payload
