"""Find high-overlap coverage while keeping each publisher's article addressable."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from app.article_metadata import restore_metadata
from app.discovery import search_text
from app.intelligence import GENERIC_TERMS, references, story_identity
from app.sources import BY_ID

COVERAGE_WINDOW = timedelta(hours=72)
COVERAGE_TYPES = {"reporting", "publisher", "advisory"}
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Headline:
    published: datetime
    language: str
    words: frozenset[str]
    numbers: frozenset[str]
    references: frozenset[str]


def headline(article):
    source = BY_ID.get(article.get("source_id"))
    if not source or source.coverage not in COVERAGE_TYPES or source.kind in {"video", "research"}:
        return None
    try:
        published = datetime.fromisoformat(article["published_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if published.utcoffset() is None:
        return None
    title = article["title"]
    return Headline(published, source.language,
                    frozenset(word for word in search_text(title).split() if len(word) >= 3
                              and not word.isdecimal() and word not in GENERIC_TERMS),
                    frozenset(NUMBER.findall(title)), frozenset(references(article)))


def coverage_match(left, right):
    if not left or not right or abs(left.published - right.published) > COVERAGE_WINDOW:
        return None
    if shared := left.references & right.references:
        return 1.0, "Shared reference " + min(shared)
    if (left.language != right.language or left.numbers != right.numbers
            or (left.references and right.references)):
        return None
    shared = left.words & right.words
    similarity = len(shared) / max(1, len(left.words | right.words))
    shorter = min(len(left.words), len(right.words))
    close_match = len(shared) >= 4 and similarity >= .72
    comparable_reports = len(shared) >= 5 and similarity >= .5 and len(shared) >= .7 * shorter
    if close_match or comparable_reports:
        return similarity, "Closely matching headlines"
    return None


def compare_coverage(article, candidates, limit=5):
    anchor = headline(article)
    if not anchor:
        return []
    ranked = []
    for row in candidates:
        if row["id"] != article["id"] and row["publisher"] != article["publisher"]:
            if match := coverage_match(anchor, headline(row)):
                ranked.append((match[0], row["published_at"], row["id"], match[1], row))
    publishers, links = {article["publisher"]}, {story_identity(article)}
    result = []
    for _, _, _, reason, row in sorted(ranked, key=lambda item: item[:3], reverse=True):
        identity = story_identity(restore_metadata(row))
        if row["publisher"] in publishers or identity in links:
            continue
        publishers.add(row["publisher"])
        links.add(identity)
        result.append(dict(row, related_reason=reason))
        if len(result) == limit:
            break
    return result
