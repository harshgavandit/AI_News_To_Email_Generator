"""Official public community APIs. No arbitrary URL fetching or article scraping."""
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

import httpx

from app.article_metadata import metadata_for, public_link
from app.sanitation import sanitize_story_excerpt, sanitize_text

HN_BASE = "https://hacker-news.firebaseio.com/v0"
HEADERS = {"User-Agent": "InformaAI/1.0 (+https://github.com/harshgavandit/AI_News_To_Email_Generator)",
           "Accept": "application/json"}
GENERAL_DEV_FEEDS = frozenset({"dev-community", "dev-latest"})
DEV_TECH_TERMS = re.compile(
    r"\b(?:software|programming|developer|coding|debugging|algorithms?|compilers?|"
    r"python|javascript|typescript|golang|rust|java|kotlin|swift|php|ruby|"
    r"react|angular|svelte|next\.js|webassembly|frontend|backend|api|"
    r"android|ios|web accessibility|screen readers?|design systems?|"
    r"databases?|postgres(?:ql)?|sqlite|mysql|mongodb|redis|sql|"
    r"devops|docker|kubernetes|linux|open[ -]?source|git(?:hub|lab)?|"
    r"cloud|serverless|distributed systems?|cybersecurity|vulnerabilit(?:y|ies)|encryption|"
    r"ai|llms?|machine learning|artificial intelligence|chatgpt|"
    r"robotics|semiconductors?|risc[ -]v|firmware|embedded systems?)\b", re.I,
)
DEV_TECH_TAGS = frozenset({"webdev", "machinelearning", "datascience", "computerscience",
                           "csharp", "cpp", "go", "node", "nodejs", "dotnet", "aws", "azure",
                           "security", "testing", "opensource", "programming", "cloudcomputing"})


def dev_article_in_scope(article):
    """The mixed DEV streams can carry non-technical posts and local ads."""
    if DEV_TECH_TERMS.search(f"{article['title']} {article.get('description', '')}"):
        return True
    tags = set(metadata_for(article).get("tags", ()))
    return bool(tags & DEV_TECH_TAGS or any(DEV_TECH_TERMS.fullmatch(tag) for tag in tags))


def record(source, title, url, published, description="", **metadata):
    title = sanitize_text(title, limit=500)
    if not title or not public_link(url):
        raise ValueError("Invalid article")
    date = datetime.fromisoformat(published.replace("Z", "+00:00")) if isinstance(published, str) else published
    if date.tzinfo is None or date > datetime.now(UTC) + timedelta(minutes=5):
        raise ValueError("Invalid publication date")
    tags = metadata.get("tags", [])
    return {"id": hashlib.sha256(url.encode()).hexdigest()[:20], "title": title, "url": url,
            "description": sanitize_story_excerpt(description, source.group, video_fallback=False),
            "published_at": date.astimezone(UTC).isoformat(), "source": source.group, "source_id": source.id,
            "publisher": source.label, "kind": source.kind,
            "category": " | ".join(sanitize_text(tag, 40) for tag in tags[:5])[:100] or "News",
            **metadata_for(metadata)}


def read_dev(source, fetch):
    payload = json.loads(fetch(source.url))
    if not isinstance(payload, list):
        raise ValueError("Invalid DEV response")
    records = []
    valid_record = False
    for item in payload[:100]:
        try:
            if not isinstance(item, dict) or not str(item.get("url", "")).startswith("https://dev.to/"):
                continue
            user = item.get("user") or {}
            username = user.get("username", "") if isinstance(user, dict) else ""
            profile = f"https://dev.to/{username}" if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", username) else ""
            tags = item.get("tag_list") or []
            if not isinstance(tags, list):
                tags = []
            article = record(source, item["title"], item["url"], item["published_at"], item.get("description", ""),
                author=user.get("name", "") if isinstance(user, dict) else "", author_url=profile, tags=tags,
                original_url=item.get("canonical_url"), thumbnail_url=item.get("cover_image"),
                points=item.get("public_reactions_count"), comments_count=item.get("comments_count"),
                reading_time_minutes=item.get("reading_time_minutes"))
            valid_record = True
            if source.id not in GENERAL_DEV_FEEDS or dev_article_in_scope(article):
                records.append(article)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    if payload and not valid_record:
        raise ValueError("No eligible DEV articles")
    return records


async def hn_records(source):
    semaphore = asyncio.Semaphore(6)
    fetched = {}
    ids = []
    backoff = None
    try:
        async with asyncio.timeout(12), httpx.AsyncClient(timeout=httpx.Timeout(4, connect=3), trust_env=False,
                                                         follow_redirects=False, headers=HEADERS) as client:
            async def get(path):
                nonlocal backoff
                async with semaphore:
                    if backoff is not None:
                        raise backoff
                    async with client.stream("GET", f"{HN_BASE}/{path}.json") as response:
                        try:
                            response.raise_for_status()
                        except httpx.HTTPStatusError as error:
                            if response.status_code == 429 or (response.status_code == 503 and "Retry-After" in response.headers):
                                backoff = error
                            raise
                        body = bytearray()
                        async for chunk in response.aiter_bytes(65536):
                            body.extend(chunk)
                            if len(body) > 500_000:
                                raise ValueError("Community response too large")
                    return json.loads(body)

            lists = await asyncio.gather(*(get(path) for path in ("topstories", "newstories", "showstories")),
                                         return_exceptions=True)
            if backoff is not None:
                raise backoff
            if not any(isinstance(ids, list) for ids in lists):
                raise ValueError("Invalid story list")
            lists = [ids if isinstance(ids, list) else [] for ids in lists]
            ids = list(dict.fromkeys(ident for values, cap in zip(lists, (32, 24, 16)) for ident in values[:cap]
                                     if type(ident) is int and 0 < ident < 10**12))
            async def get_item(ident):
                try:
                    fetched[ident] = await get(f"item/{ident}")
                except (httpx.HTTPError, ValueError, OSError):
                    pass
            await asyncio.gather(*(get_item(ident) for ident in ids))
    except TimeoutError:
        # Keep completed items when the total budget expires; one slow tail
        # must not discard an otherwise usable community snapshot.
        if not fetched and backoff is None:
            raise
    if backoff is not None:
        raise backoff
    records = []
    for ident, item in fetched.items():
        try:
            if not isinstance(item, dict) or item.get("deleted") or item.get("dead") or item.get("type") != "story":
                continue
            if item.get("id") != ident:
                continue
            discussion = f"https://news.ycombinator.com/item?id={ident}"
            records.append(record(source, item["title"], discussion, datetime.fromtimestamp(item["time"], UTC),
                # HN text is the submitter's text, not the linked publisher's reporting.
                author=item.get("by"), original_url=item.get("url"), discussion_url=discussion,
                points=item.get("score"), comments_count=item.get("descendants")))
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            continue
    if ids and not records:
        raise ValueError("No eligible Hacker News stories")
    return records


def read_community(source, fetch):
    try:
        items = read_dev(source, fetch) if source.integration == "dev-api" else asyncio.run(hn_records(source))
        return items, dict(source.public(), available=True, count=len(items))
    except httpx.HTTPStatusError as error:
        from app.news import http_failure
        return [], dict(source.public(), available=False, count=0, **http_failure(error))
    except (httpx.HTTPError, ValueError, TypeError, OSError, TimeoutError):
        return [], dict(source.public(), available=False, count=0, error="api_unavailable")
