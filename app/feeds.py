"""Public RSS 2.0 feeds: latest stories, topics, technologies, any search, and Curiosity Cards.

Items carry the headline, a short publisher excerpt and a link to the original publisher, never the
full article, matching the site. Feeds are cached at the edge and answer conditional requests.
"""
from datetime import UTC, datetime
from email.utils import format_datetime
import hashlib
import logging
import os
from typing import Annotated
from xml.etree.ElementTree import Element, SubElement, tostring

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app import technology
from app.article_language import is_not_foreign_article
from app.cache import Cache
from app.coverage import TOPICS, public_article
from app.discovery import search_terms, search_text
from app.launch_store import get_store
from app.sources import LANGUAGES

logger = logging.getLogger(__name__)
router = APIRouter()
_feed_cache = Cache("rss-feeds-v1")
FEED_TTL = 900
ITEMS = 30
ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/elements/1.1/"
DESCRIPTION_LIMIT = 600


def site() -> str:
    return (os.getenv("PUBLIC_ORIGIN") or "https://getinformdaily.com").rstrip("/")


def directory():
    """Every fixed feed, for the feeds page and API docs."""
    return {
        "latest": {"title": "Latest technology news", "path": "/feeds/latest.xml"},
        "curiosity": {"title": "Curiosity Cards", "path": "/feeds/curiosity.xml"},
        "recap": {"title": "This week in tech", "path": "/feeds/recap.xml"},
        "topics": [{"id": key, "title": label, "path": f"/feeds/topic/{key}.xml"} for key, label in TOPICS.items()],
        "technologies": [{"id": key, "title": tech.name, "path": f"/feeds/technology/{key}.xml"}
                         for key, tech in technology.TECHNOLOGIES.items()],
        "search": {"title": "Any search", "path": "/feeds/search.xml?q={terms}"},
    }


def _date(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _clip(text, limit=DESCRIPTION_LIMIT):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def render(title, description, path, page_url, items):
    """Build RSS 2.0. ElementTree escapes every value, so publisher text cannot inject markup."""
    root = Element("rss", {"version": "2.0", "xmlns:atom": ATOM, "xmlns:dc": DC})
    channel = SubElement(root, "channel")
    SubElement(channel, "title").text = f"{title} | Informa AI"
    SubElement(channel, "link").text = site() + page_url
    SubElement(channel, "description").text = description
    SubElement(channel, "language").text = "en"
    SubElement(channel, "ttl").text = str(FEED_TTL // 60)
    SubElement(channel, "atom:link", {"href": site() + path, "rel": "self", "type": "application/rss+xml"})
    image = SubElement(channel, "image")
    SubElement(image, "url").text = site() + "/icons/icon-192.png"
    SubElement(image, "title").text = f"{title} | Informa AI"
    SubElement(image, "link").text = site() + page_url
    dates = [moment for item in items if (moment := item.get("date"))]
    if dates:
        SubElement(channel, "lastBuildDate").text = format_datetime(max(dates))
    for item in items:
        entry = SubElement(channel, "item")
        SubElement(entry, "title").text = item["title"]
        SubElement(entry, "link").text = item["link"]
        SubElement(entry, "guid", {"isPermaLink": "false"}).text = f"informa:{item['id']}"
        if item.get("date"):
            SubElement(entry, "pubDate").text = format_datetime(item["date"])
        if item.get("description"):
            SubElement(entry, "description").text = item["description"]
        if item.get("category"):
            SubElement(entry, "category").text = item["category"]
        if item.get("source"):
            SubElement(entry, "dc:creator").text = item["source"]
    return tostring(root, encoding="utf-8", xml_declaration=True)


def story_items(rows):
    items, seen = [], set()
    for row in rows:
        link = row.get("original_url") or row.get("sourceUrl") or row.get("url")
        if not link or not str(link).startswith(("https://", "http://")) or row["id"] in seen:
            continue
        seen.add(row["id"])
        publisher = row.get("sourceName") or row.get("publisher") or ""
        excerpt = row.get("cleanSummary") if row.get("summary_basis", "publisher_excerpt") == "publisher_excerpt" else row.get("excerpt")
        summary = _clip(excerpt or "")
        items.append({"id": row["id"], "title": _clip(row["title"], 300), "link": link,
                      "date": _date(row.get("publishedAt") or row.get("published_at")),
                      "description": f"{summary} — {publisher}" if summary and publisher else summary or publisher,
                      "category": TOPICS.get(row.get("category") or row.get("topic"), ""), "source": publisher})
    return items[:ITEMS]


def archive():
    store = get_store()
    if not store:
        raise HTTPException(503, "Feeds are unavailable right now.")
    return store


Language = Annotated[str, Query(max_length=16, description="Article language; English by default, or all")]


def language_filter(language):
    if language != "all" and language not in LANGUAGES:
        raise HTTPException(422, "Choose a supported language, or all.")
    return "" if language == "all" else language


def latin_headline(title):
    """Headlines mixing a Latin brand name into another script are often labelled undetermined."""
    letters = [char for char in title if char.isalpha()]
    return not letters or sum(char.isascii() or "\u00c0" <= char <= "\u024f" for char in letters) / len(letters) >= .8


def readable(article, language):
    # English feeds keep short headlines the detector cannot classify, such as "Release v1.36.0".
    return is_not_foreign_article(article) and latin_headline(article.get("title") or "") if language == "en" else True


def page_rows(*, hours, topic="all", query="", language="en"):
    page = archive().page(hours=hours, source="all", query=query, kind="all", publisher="", limit=50,
                          cursor=None, topic=topic, sort="latest", language="" if language == "en" else language)
    return [public_article(article) for article in page["articles"] if readable(article, language)]


def curiosity_items():
    from urllib.parse import quote as quote_path
    from app.curiosity import THEMES
    from app.curiosity_api import curiosity_shelf
    labels = {ident: label for ident, label, *_ in THEMES}
    cards = []
    for card in curiosity_shelf()["cards"]:
        date = _date(card.get("published_at")) or (datetime(int(card["year"]), 1, 1, tzinfo=UTC) if card.get("year") else None)
        cards.append({"id": f"card-{card['id']}", "title": _clip(card["title"], 300),
                      "link": f"{site()}/cards/{quote_path(card['id'], safe='')}",
                      "date": date, "description": _clip(card.get("summary") or card.get("description") or ""),
                      "category": labels.get(card.get("theme"), ""), "source": card.get("publisher") or card.get("company") or ""})
    cards.sort(key=lambda item: item["date"] or datetime.min.replace(tzinfo=UTC), reverse=True)
    return cards[:ITEMS]


def respond(request: Request, key: str | None, build):
    cached, _ = _feed_cache.get(key) if key else (None, False)
    if cached is not None:
        body = cached["xml"].encode()
    else:
        body = build()
        if key:
            _feed_cache.put(key, {"xml": body.decode()}, ttl=FEED_TTL, stale=0)
    etag = 'W/"' + hashlib.sha256(body).hexdigest()[:20] + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=600",
               "Vercel-CDN-Cache-Control": f"public, s-maxage={FEED_TTL}, stale-while-revalidate=3600",
               "X-Content-Type-Options": "nosniff"}
    if etag in [tag.strip() for tag in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/rss+xml; charset=utf-8", headers=headers)


@router.get("/feeds/latest.xml", include_in_schema=False)
def latest_feed(request: Request, language: Language = "en"):
    language = language_filter(language)
    return respond(request, f"latest:{language}", lambda: render(
        "Latest technology news", "The newest technology and AI stories from reviewed publishers worldwide, with links to the originals.",
        "/feeds/latest.xml", "/", story_items(page_rows(hours=48, language=language))))


@router.get("/feeds/topic/{topic}.xml", include_in_schema=False)
def topic_feed(request: Request, topic: str, language: Language = "en"):
    if topic not in TOPICS:
        raise HTTPException(404, "Unknown topic feed.")
    language = language_filter(language)
    return respond(request, f"topic:{topic}:{language}", lambda: render(
        TOPICS[topic], f"The newest {TOPICS[topic]} stories from reviewed publishers, with links to the originals.",
        f"/feeds/topic/{topic}.xml", f"/?topic={topic}", story_items(page_rows(hours=168, topic=topic, language=language))))


@router.get("/feeds/technology/{ident}.xml", include_in_schema=False)
def technology_feed(request: Request, ident: str, language: Language = "en"):
    tech = technology.TECHNOLOGIES.get(ident)
    if not tech:
        raise HTTPException(404, "Unknown technology feed.")
    language = language_filter(language)
    rows = lambda: [row for row in technology.eligible_rows(archive(), ident, 24 * 30, limit=ITEMS * 3)  # noqa: E731
                    if not language or (row.get("language") in ("en", "und") and latin_headline(row["title"])
                                        if language == "en" else row.get("language") == language)]
    return respond(request, f"technology:{ident}:{language}", lambda: render(
        tech.name, f"Releases, advisories, incidents and news about {tech.name} from official and reviewed sources.",
        f"/feeds/technology/{ident}.xml", f"/technology.html?tech={ident}",
        story_items(rows())))


@router.get("/feeds/search.xml", include_in_schema=False)
def search_feed(request: Request, q: Annotated[str, Query(min_length=2, max_length=80)], language: Language = "en"):
    language = language_filter(language)
    phrase = search_text(q)
    if not search_terms(phrase):
        raise HTTPException(422, "Enter at least one letter or number.")
    label = " ".join(q.split())[:80]
    # Searches stay out of the shared cache, like arbitrary searches on /api/news.
    return respond(request, None, lambda: render(
        f"Search: {label}", f"The newest stories matching “{label}” from reviewed publishers.",
        f"/feeds/search.xml?q={quote(label)}", f"/?q={quote(label)}", story_items(page_rows(hours=168, query=phrase, language=language))))


@router.get("/feeds/curiosity.xml", include_in_schema=False)
def curiosity_feed(request: Request):
    return respond(request, "curiosity", lambda: render(
        "Curiosity Cards", "Real-world engineering case studies, postmortems and research on how great software is built.",
        "/feeds/curiosity.xml", "/curiosity.html", curiosity_items()))


def recap_items():
    from app import weekly_recap
    store = archive()
    try:
        weekly_recap.latest(store)  # make sure last week's snapshot exists
    except Exception as error:  # noqa: BLE001 - older recaps can still be listed
        logger.warning("recap_feed_build_failed error_type=%s", type(error).__name__)
    items = []
    for entry in weekly_recap.available(store, limit=12):
        payload = weekly_recap.load(store, entry["week"])
        start, end = weekly_recap.week_bounds(entry["week"])
        top = "; ".join(story["title"] for story in payload["top_stories"][:3])
        items.append({"id": f"recap-{entry['week']}", "title": payload["title"], "link": f"{site()}/recap.html?week={entry['week']}",
                      "date": end, "description": _clip(f"Top stories: {top}" if top else payload["notice"]),
                      "category": "Weekly recap", "source": "Informa AI"})
    return items


@router.get("/feeds/recap.xml", include_in_schema=False)
def recap_feed(request: Request):
    return respond(request, "recap", lambda: render(
        "This week in tech", "A weekly recap of the biggest technology stories, AI model launches, incidents, exploited "
        "vulnerabilities and releases.", "/feeds/recap.xml", "/recap.html", recap_items()))


@router.get("/api/feeds")
def feed_directory(response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    return directory()

