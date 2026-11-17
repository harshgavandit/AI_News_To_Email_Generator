"""Crossref journal metadata discovery. Never republishes copyrighted abstracts."""
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import threading
import time
import math

import httpx

from app.article_metadata import extract_technical_terms, metadata_for
from app.sanitation import sanitize_text

DOI = re.compile(r"10\.\d{4,9}/[^\s<>]+", re.I)
_gate = threading.Lock()
_last_request = 0.0
_blocked_until = 0.0


def read_crossref(source, fetch):
    from app.news import canonical_url, http_failure
    global _last_request, _blocked_until
    with _gate:
        if _blocked_until > time.monotonic():
            return [], dict(source.public(), available=False, count=0, error="rate_limited",
                            retry_after=math.ceil(_blocked_until - time.monotonic()))
        time.sleep(max(0, 1 - (time.monotonic() - _last_request)))
        try:
            payload = json.loads(fetch(source.url))
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429:
                _blocked_until = time.monotonic() + max(60, http_failure(error).get("retry_after", 300))
            raise
        finally:
            _last_request = time.monotonic()
    records = payload.get("message", {}).get("items")
    if not isinstance(records, list):
        raise ValueError("Invalid scholarly metadata response")
    items, seen = [], set()
    now = datetime.now(UTC)
    for record in records[:50]:
        try:
            if record.get("type") != "journal-article":
                continue
            doi = record.get("DOI", "").lower()
            if not DOI.fullmatch(doi):
                continue
            date = (record.get("published-online") or record.get("published") or {}).get("date-parts", [[]])[0]
            if len(date) != 3:
                continue  # Never manufacture a day for year-only or month-only metadata.
            published = datetime(*date, tzinfo=UTC)
            if not now - timedelta(days=90) <= published <= now:
                continue
            title = sanitize_text(record.get("title", [""])[0], limit=500)
            if not title:
                continue
            url = canonical_url("https://doi.org/" + doi)
            ident = hashlib.sha256(url.encode()).hexdigest()[:20]
            if ident in seen:
                continue
            authors = record.get("author", [])
            names = [" ".join(filter(None, (author.get("given"), author.get("family")))) for author in authors[:4]]
            items.append({"id": ident, "url": url, "title": title, "description": "",
                "published_at": published.isoformat(), "publication_date_precision": "day",
                "source_id": source.id, "source": source.group, "publisher": source.label, "kind": "research",
                "category": "Journal metadata", **metadata_for({"author": ", ".join(names),
                    "publication_date_precision": "day", "technical_terms": extract_technical_terms(record.get("abstract", ""))})})
            seen.add(ident)
        except (AttributeError, TypeError, ValueError, IndexError):
            continue
    return items, dict(source.public(), available=True, count=len(items), observed_entries=len(records),
        rejected_entries=len(records) - len(items), latest_published_at=max((item["published_at"] for item in items), default=None))
