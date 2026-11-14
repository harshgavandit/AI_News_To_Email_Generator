"""Shared search and ordering rules for the archive and direct RSS mode."""
import hashlib
import json
import re
from typing import Literal

SortOrder = Literal["latest", "oldest", "relevance"]
MAX_SEARCH_TERMS = 12


def search_terms(query):
    return tuple(dict.fromkeys(re.findall(r"[\w+#-]+", query.lower())))[:MAX_SEARCH_TERMS]


def relevance_score(article, query, terms):
    title, description, publisher = (article.get(field, "").lower() for field in ("title", "description", "publisher"))
    if not all(term in title or term in description or term in publisher for term in terms):
        return None
    return 10 * int(query.lower() in title) + sum(3 * int(term in title) + int(term in publisher) for term in terms)


def page_fingerprint(hours, source, query, kind, publisher, topic, region, sort):
    return hashlib.sha256(json.dumps([hours, source, query, kind, publisher, topic, region, sort]).encode()).hexdigest()[:16]
