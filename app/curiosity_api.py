"""Curiosity Cards browsing API: paged, filtered and searchable on the server.

The page used to download every card (~400 KB) and filter in the browser. Now the server keeps one cached
"shelf" of cards, filters and searches it, and returns one page at a time with an opaque cursor. A cursor
names the shelf version it was issued for; when the shelf is rebuilt the cursor is refused with 409 so the
client restarts from the first page instead of silently skipping or repeating cards.
"""
import base64
from copy import deepcopy
import hashlib
import json
import logging
import re
import threading
from typing import Annotated, Literal

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.cache import Cache
from app.curiosity import (COLLECTIONS, LESSONS, FORMATS, LEVELS, MAX_CURIOSITY_CARDS, ORIGINS, PROBLEM_LABELS, SEEDS_BY_ID, SORTS, THEME_LABELS,
                           _card, build_curiosity_cards, curiosity_facets, filter_cards, saved_curiosity_article)
from app.launch_store import get_store

logger = logging.getLogger(__name__)
router = APIRouter()

PAGE_DEFAULT = 24
PAGE_MAX = 48
SHELF_TTL = 1800
SHELF_STALE = 6 * 3600
CARD_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$"
_shelf_cache = Cache("curiosity-shelf-v1")
_shelf_lock = threading.Lock()


def _version(cards):
    return hashlib.sha256("\n".join(card["id"] for card in cards).encode()).hexdigest()[:16]


def _rebuild_shelf():
    cards = build_curiosity_cards(get_store(), limit=MAX_CURIOSITY_CARDS)
    value = {"cards": cards, "version": _version(cards), "facets": curiosity_facets(cards)}
    _shelf_cache.put("shelf", value, ttl=SHELF_TTL, stale=SHELF_STALE)
    return value


def _refresh_in_background():
    """Rebuild a stale shelf off the request path; readers keep the previous shelf meanwhile."""
    if not _shelf_lock.acquire(blocking=False):
        return  # Another request is already rebuilding it.

    def work():
        try:
            _rebuild_shelf()
        except Exception as error:
            logger.warning("curiosity_shelf_refresh_failed error_type=%s", type(error).__name__)
        finally:
            _shelf_lock.release()

    threading.Thread(target=work, name="curiosity-shelf-refresh", daemon=True).start()


def curiosity_shelf():
    """Every card the collection can show, in featured order.

    Fresh for half an hour; after that the previous shelf is served while a new one is built in the
    background (stale-while-revalidate), so only a cold start ever waits for the model-written summaries.
    """
    value, stale = _shelf_cache.get("shelf")
    if value is not None:
        if stale:
            _refresh_in_background()
        return value
    with _shelf_lock:
        value, _ = _shelf_cache.get("shelf")
        return value if value is not None else _rebuild_shelf()


def encode_cursor(version, offset):
    return base64.urlsafe_b64encode(f"{version}.{offset}".encode()).decode().rstrip("=")


def decode_cursor(cursor):
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        version, offset = raw.split(".", 1)
        offset = int(offset)
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(400, "That page link is not valid. Start again from the first page.") from error
    if not re.fullmatch(r"[0-9a-f]{16}", version) or not 0 < offset <= MAX_CURIOSITY_CARDS:
        raise HTTPException(400, "That page link is not valid. Start again from the first page.")
    return version, offset


def _choice(value, allowed, name):
    if value != "all" and value not in allowed:
        raise HTTPException(422, f"Unknown {name}.")
    return value


def _conditional(request: Request, response: Response, payload, max_age):
    """Weak ETag over the response body; a matching If-None-Match gets an empty 304."""
    etag = 'W/"' + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24] + '"'
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}, stale-while-revalidate={max_age * 5}",
               "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


@router.get("/api/curiosity/cards")
def curiosity_cards_page(
    request: Request, response: Response,
    limit: Annotated[int, Query(ge=1, le=PAGE_MAX)] = PAGE_DEFAULT,
    cursor: Annotated[str, Query(max_length=64, pattern=r"^[A-Za-z0-9_-]*$")] = "",
    theme: Annotated[str, Query(max_length=40)] = "all",
    problem: Annotated[str, Query(max_length=40)] = "all",
    format: Annotated[str, Query(max_length=40)] = "all",
    level: Annotated[str, Query(max_length=40)] = "all",
    company: Annotated[str, Query(max_length=80)] = "all",
    origin: Literal["all", "fresh", "classic"] = "all",
    sort: Literal["featured", "newest"] = "featured",
    q: Annotated[str, Query(max_length=80)] = "",
):
    """One page of Curiosity Cards with whole-shelf facets. Reads the archive only; never fetches publishers."""
    filters = {"theme": _choice(theme, THEME_LABELS, "theme"), "problem": _choice(problem, PROBLEM_LABELS, "problem"),
               "format": _choice(format, FORMATS, "format"), "level": _choice(level, LEVELS, "level"),
               "company": company.strip() or "all", "origin": origin, "sort": sort, "query": " ".join(q.split())[:80]}
    shelf = curiosity_shelf()
    offset = 0
    if cursor:
        version, offset = decode_cursor(cursor)
        if version != shelf["version"]:
            raise HTTPException(409, "The collection was refreshed. Load it again from the first page.")
    matches = filter_cards(shelf["cards"], **filters)
    page = matches[offset:offset + limit]
    following = offset + len(page)
    payload = {
        "cards": page, "total": len(matches), "offset": offset, "limit": limit, "version": shelf["version"],
        "next_cursor": encode_cursor(shelf["version"], following) if following < len(matches) else None,
        "facets": shelf["facets"],
        "labels": {"themes": THEME_LABELS, "problems": PROBLEM_LABELS, "formats": FORMATS, "levels": LEVELS},
        "filters": {**{key: value for key, value in filters.items() if key != "query"}, "q": filters["query"]},
    }
    return _conditional(request, response, payload, max_age=60)


def find_card(ident):
    """A card by id: from the shelf, then reviewed seeds, then saved cards that have left the shelf."""
    if ident in SEEDS_BY_ID:
        return _card(deepcopy(SEEDS_BY_ID[ident]), {})
    shelf = curiosity_shelf()
    card = next((card for card in shelf["cards"] if card["id"] == ident), None)
    if card:
        return card
    saved = saved_curiosity_article(get_store(), ident)
    return {**saved, "seed": True, "archived": True} if saved else None


@router.get("/api/curiosity/cards/{card_id}")
def curiosity_card(request: Request, response: Response,
                   card_id: Annotated[str, Path(max_length=96, pattern=CARD_ID)]):
    """One Curiosity Card, for shareable card links."""
    card = find_card(card_id)
    if not card:
        raise HTTPException(404, "That Curiosity Card is no longer in the collection.")
    return _conditional(request, response, {"card": card}, max_age=300)


# --- Anonymous usage counts -------------------------------------------------------------------------------
# The browser sends these only when the reader has turned on audience analytics (off by default) and no
# Global Privacy Control or Do Not Track signal is present. The server stores daily counts per card, list and
# surface: never an IP address, user agent, identifier or timestamp finer than a day.
CARD_EVENTS = {"card_view", "open_source", "read_next", "share"}
LIST_EVENTS = {"list_open", "lesson_open"}
SURFACES = {"home", "collection", "card_page"}
LIST_IDS = {ident for ident, *_ in COLLECTIONS} | {f"lesson-{ident}" for ident, *_ in LESSONS}
POPULAR_MIN_EVENTS = 20
POPULAR_MIN_PER_CARD = 3


class CuriosityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["card_view", "open_source", "read_next", "share", "list_open", "lesson_open"]
    surface: Literal["home", "collection", "card_page"]
    card_id: str = Field(default="", max_length=96)
    list_id: str = Field(default="", max_length=96)


class CuriosityEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[CuriosityEvent] = Field(min_length=1, max_length=20)


def known_card_ids():
    return set(SEEDS_BY_ID) | {card["id"] for card in curiosity_shelf()["cards"]}


def event_rows(events, day, known_cards):
    """Only well-formed events about cards and lists that exist; everything else is dropped silently."""
    rows = []
    for event in events:
        if event.type in CARD_EVENTS and re.fullmatch(CARD_ID, event.card_id) and event.card_id in known_cards:
            rows.append((day, event.type, event.card_id, "", event.surface))
        elif event.type in LIST_EVENTS and event.list_id in LIST_IDS:
            rows.append((day, event.type, "", event.list_id, event.surface))
    return rows


def _privacy_signal(request: Request):
    return request.headers.get("sec-gpc") == "1" or request.headers.get("dnt") == "1"


@router.post("/api/curiosity/events", status_code=204)
def record_curiosity_events(request: Request, body: CuriosityEvents):
    """Count what readers open. Always answers 204 so the response says nothing about what was counted."""
    from app.server import rate_limit  # Imported here: the server module includes this router.

    if _privacy_signal(request):
        return Response(status_code=204)
    rate_limit(request, "curiosity-events", 60)
    store = get_store()
    rows = event_rows(body.events, datetime.now(UTC).date().isoformat(), known_card_ids())
    if store and rows:
        try:
            store.record_curiosity_events(rows)
        except Exception as error:  # Counting must never break reading.
            logger.warning("curiosity_events_failed error_type=%s", type(error).__name__)
    return Response(status_code=204)


_popular_cache = Cache("curiosity-popular-v1")


def popular_cards(store, days=30, limit=6):
    """Cards readers opened most in the window, only once there is enough data to mean something."""
    if not store:
        return []
    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    rows = store.curiosity_event_totals(since, events=("card_view", "open_source", "read_next"), limit=50)
    if sum(row["count"] for row in rows) < POPULAR_MIN_EVENTS:
        return []
    shelf = {card["id"]: card for card in curiosity_shelf()["cards"]}
    picks = []
    for row in rows:
        card = shelf.get(row["id"]) or (find_card(row["id"]) if row["id"] in SEEDS_BY_ID else None)
        if card and row["count"] >= POPULAR_MIN_PER_CARD:
            picks.append({"id": card["id"], "title": card["title"], "company": card.get("company") or card.get("publisher") or "",
                          "url": card.get("url", "")})
        if len(picks) >= limit:
            break
    return picks


@router.get("/api/curiosity/popular")
def curiosity_popular(request: Request, response: Response, days: Annotated[int, Query(ge=1, le=90)] = 30):
    """Most-opened cards in the window, by rank only (counts are not published)."""
    key = str(days)
    cards, _ = _popular_cache.get(key)
    if cards is None:
        try:
            cards = {"cards": popular_cards(get_store(), days=days)}
        except Exception as error:
            logger.warning("curiosity_popular_failed error_type=%s", type(error).__name__)
            cards = {"cards": []}
        _popular_cache.put(key, cards, ttl=600)
    return _conditional(request, response, {**cards, "window_days": days}, max_age=300)

