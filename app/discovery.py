"""Shared search and ordering rules for the archive and direct RSS mode."""
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import unicodedata
from typing import Literal

from app.coverage import REGIONS, TOPICS, region_id
from app.sources import BY_ID

SortOrder = Literal["latest", "oldest", "relevance"]
MAX_SEARCH_TERMS = 12
COVERAGE_TYPES = {
    "reporting": "Independent reporting",
    "publisher": "Official publications",
    "advisory": "Security advisories",
    "preprint": "Research preprints",
    "status": "Service status",
    "discussion": "Community discussion",
}


class InvalidCursor(ValueError):
    pass


def page_window(cursor, fingerprint, *, ranked):
    now = datetime.now(UTC)
    if cursor is None:
        return now, None
    try:
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(value, list) or value[-1] != fingerprint:
            raise ValueError
        keys = 3 if ranked else 2
        # Accept cursors issued before the publication window was carried in the token.
        if len(value) == keys + 1:
            anchor = now
            marker = value[:-1]
        elif len(value) == keys + 2:
            anchor = datetime.fromisoformat(value[-2])
            if anchor.utcoffset() != timedelta(0) or not now - timedelta(hours=24) <= anchor <= now + timedelta(seconds=10):
                raise ValueError
            marker = value[:-2]
        else:
            raise ValueError
        date, ident = marker[-2:]
        if not isinstance(date, str) or not isinstance(ident, str) or not 1 <= len(ident) <= 40:
            raise ValueError
        published = datetime.fromisoformat(date)
        if published.utcoffset() != timedelta(0) or published > anchor:
            raise ValueError
        if ranked and (type(marker[0]) is not int or not 0 <= marker[0] <= 10 + 4 * MAX_SEARCH_TERMS):
            raise ValueError
        return anchor, marker
    except (TypeError, ValueError, IndexError) as exc:
        raise InvalidCursor from exc


def page_result(rows, total, limit, fingerprint, anchor):
    shown = rows[:limit]
    cursor = None
    if len(rows) > limit:
        last = shown[-1]
        marker = [last["published_at"], last["id"], anchor.isoformat(), fingerprint]
        if "search_score" in last:
            marker.insert(0, last["search_score"])
        cursor = base64.urlsafe_b64encode(json.dumps(marker, separators=(",", ":")).encode()).decode()
    return {"articles": [{k: v for k, v in row.items() if k != "search_score"} for row in shown],
            "total": total, "next_cursor": cursor, "window_ends_at": anchor.isoformat()}


def search_terms(query):
    return tuple(dict.fromkeys(part for part in search_text(query).split()
                               if any(c.isalnum() for c in part)))[:MAX_SEARCH_TERMS]


def search_text(text):
    """Fold accents on Latin letters and retain letters and marks from other scripts."""
    text = unicodedata.normalize("NFKD", text).casefold()
    normalized = []
    latin = False
    for char in text:
        category = unicodedata.category(char)[0]
        if category == "M":
            if not latin:
                normalized.append(char)
            continue
        latin = category == "L" and unicodedata.name(char, "").startswith("LATIN ")
        normalized.append(char if category in {"L", "N"} or char in "+#" else " ")
    return " ".join("".join(normalized).split())


def relevance_score(article, query, terms):
    title, description, publisher = (search_text(article.get(field, "")) for field in ("title", "description", "publisher"))
    if not all(term in title or term in description or term in publisher for term in terms):
        return None
    return 10 * int(query in title) + sum(3 * int(term in title) + int(term in publisher) for term in terms)


def page_fingerprint(hours, source, query, kind, publisher, topic, region, sort, coverage=""):
    return hashlib.sha256(json.dumps([hours, source, query, kind, publisher, topic, region, sort, coverage]).encode()).hexdigest()[:16]


def catalog_filters(region="", coverage=""):
    """Translate publisher coverage filters to reviewed source IDs."""
    return tuple(source.id for source in BY_ID.values()
                 if (not region or region_id(source.region) == region)
                 and (not coverage or source.coverage == coverage))


def facet_counts(groups, *, source, topic, region):
    topics = dict.fromkeys(TOPICS, 0)
    regions = dict.fromkeys(REGIONS, 0)
    sources = {"all": 0}
    total = 0
    for source_id, group, category, count in groups:
        entry = BY_ID.get(source_id)
        bucket = region_id(entry.region if entry else "Global")
        # A prior deployment can finish an in-flight insert during a rolling release.
        if category is None:
            category = "all"  # Until the next refresh backfills it, include it in unfiltered totals only.
        in_region = not region or bucket == region
        in_topic = topic in ("all", category)
        if in_region and in_topic:
            sources["all"] += count
            sources[group] = sources.get(group, 0) + count
        if source not in ("all", group, source_id):
            continue
        if in_region and category in topics:
            topics[category] += count
        if in_topic:
            regions[bucket] += count
        if in_region and in_topic:
            total += count
    return {"total": total, "source_counts": sources,
            "facets": {"topics": {"all": sum(topics.values()), **topics},
                       "regions": {"all": sum(regions.values()), **regions}}}
