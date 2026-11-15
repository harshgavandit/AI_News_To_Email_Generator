"""Shared search and ordering rules for the archive and direct RSS mode."""
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
from typing import Literal

SortOrder = Literal["latest", "oldest", "relevance"]
MAX_SEARCH_TERMS = 12


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
    return tuple(dict.fromkeys(re.findall(r"[\w+#-]+", query.lower())))[:MAX_SEARCH_TERMS]


def relevance_score(article, query, terms):
    title, description, publisher = (article.get(field, "").lower() for field in ("title", "description", "publisher"))
    if not all(term in title or term in description or term in publisher for term in terms):
        return None
    return 10 * int(query.lower() in title) + sum(3 * int(term in title) + int(term in publisher) for term in terms)


def page_fingerprint(hours, source, query, kind, publisher, topic, region, sort):
    return hashlib.sha256(json.dumps([hours, source, query, kind, publisher, topic, region, sort]).encode()).hexdigest()[:16]
