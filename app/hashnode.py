"""Anonymous Hashnode discovery. Public metadata only; no Pro-gated post reads."""
import asyncio
from datetime import UTC, datetime, timedelta
import json
import re

import httpx

from app.community import HEADERS, record
from app.news import canonical_url

ENDPOINT = "https://gql-beta.hashnode.com/"
PAGE_SIZE = 20
MAX_PAGES = 6
MAX_PAGE_BYTES = 1_500_000
QUERY = """query InformaDiscovery($after: String) {
  feed(first: 20, after: $after) {
    edges { node { id slug title brief url publishedAt canonicalUrl readTimeInMinutes
      author { username name } tags { name slug } coverImage { url } } }
    pageInfo { hasNextPage endCursor }
  }
}"""
TECH = re.compile(r"\b(?:ai|artificial intelligence|machine learning|programming|software|developer|development|"
    r"python|javascript|typescript|react|rust|golang|java|cloud|devops|kubernetes|docker|security|cybersecurity|"
    r"database|data engineering|linux|open source|frontend|backend|api|web|coding|system design|hardware|"
    r"research|engineering|startup|computer science|blockchain|quantum|robotics)\b", re.I)


async def fetch_page(client, after):
    async with client.stream("POST", ENDPOINT, json={"query": QUERY, "variables": {"after": after}}) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes(65536):
            body.extend(chunk)
            if len(body) > MAX_PAGE_BYTES:
                raise ValueError("Hashnode response too large")
    data = json.loads(body)
    if not isinstance(data, dict) or data.get("errors"):
        raise ValueError("Hashnode query unavailable")
    payload = data.get("data")
    feed = payload.get("feed") if isinstance(payload, dict) else None
    if not isinstance(feed, dict) or not isinstance(feed.get("edges"), list) or len(feed["edges"]) > PAGE_SIZE:
        raise ValueError("Invalid Hashnode feed")
    return feed


def normalize_post(source, item):
    if not isinstance(item, dict):
        raise ValueError("Invalid post")
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag.get("slug") or tag.get("name") or "") for tag in tags[:12] if isinstance(tag, dict)]
    if not TECH.search(" ".join([str(item.get("title", "")), *tags]).replace("-", " ")):
        return None
    published = datetime.fromisoformat(str(item.get("publishedAt", "")).replace("Z", "+00:00"))
    now = datetime.now(UTC)
    if published.tzinfo is None or not now - timedelta(days=30) <= published <= now:
        return None
    author = item.get("author") or {}
    image = item.get("coverImage") or {}
    username = author.get("username", "") if isinstance(author, dict) else ""
    author_url = f"https://hashnode.com/@{username}" if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", username) else ""
    url = canonical_url(item["url"])
    return record(source, item["title"], url, published, item.get("brief", ""),
        author=author.get("name", "") if isinstance(author, dict) else "", author_url=author_url, tags=tags,
        original_url=item.get("canonicalUrl"), thumbnail_url=image.get("url") if isinstance(image, dict) else "",
        reading_time_minutes=item.get("readTimeInMinutes"))


async def collect(source):
    records, cursors, after, completed = {}, set(), None, 0
    try:
        async with asyncio.timeout(18), httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3), trust_env=False,
                follow_redirects=False, headers={**HEADERS, "x-hashnode-client": "informa-ai"}) as client:
            for _ in range(MAX_PAGES):
                feed = await fetch_page(client, after)
                completed += 1
                for edge in feed["edges"]:
                    try:
                        item = normalize_post(source, edge.get("node") if isinstance(edge, dict) else None)
                        if item:
                            records.setdefault(item["id"], item)
                    except (ValueError, TypeError, KeyError, OverflowError):
                        continue
                page = feed.get("pageInfo") or {}
                if not isinstance(page, dict):
                    raise ValueError("Invalid Hashnode pagination")
                after = page.get("endCursor") if isinstance(page, dict) else None
                if (not page.get("hasNextPage") or not isinstance(after, str) or not 1 <= len(after) <= 500
                        or after in cursors):
                    break
                cursors.add(after)
    except (httpx.HTTPError, ValueError, TypeError, OSError, TimeoutError):
        if not completed:
            raise
    return list(records.values())


def read_hashnode(source):
    try:
        items = asyncio.run(collect(source))
        return items, dict(source.public(), available=True, count=len(items),
            latest_published_at=max((row["published_at"] for row in items), default=None))
    except (httpx.HTTPError, ValueError, TypeError, OSError, TimeoutError):
        return [], dict(source.public(), available=False, count=0, error="api_unavailable")
