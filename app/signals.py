"""Explainable priority signals from recent source material, not verified breaking alerts."""
from datetime import UTC, datetime, timedelta

from app.coverage import public_article
from app.intelligence import story_identity
from app.sources import BY_ID
from app.story_coverage import frontpage_match, headline
from app.news_signals import COMMERCE, COMPILED, news_score

RULES = tuple((key if key in {"security", "outage"} else "industry", label, matcher)
              for key, label, _, matcher in COMPILED)


def priority_signals(rows, *, now=None, limit=6, represented=()):
    now = now or datetime.now(UTC)
    candidates = []
    for row in rows:
        source = BY_ID.get(row.get("source_id"))
        if not source or source.coverage not in {"reporting", "advisory", "publisher", "release"} or COMMERCE.search(row["title"]):
            continue
        published = datetime.fromisoformat(row["published_at"])
        if not now - timedelta(hours=24) <= published <= now:
            continue
        material = row["title"] + " " + row.get("description", "")[:500]
        rule = next((rule for rule in RULES if rule[2].search(material)), None)
        if not rule:
            continue
        score = news_score(row, now) + (6 if source.coverage == "advisory" else 0)
        candidates.append((score, published, row["id"], rule, row))
    picked, identities, publishers, headings = [], set(), set(), list(represented)
    for _, _, _, rule, row in sorted(candidates, reverse=True):
        source = BY_ID[row["source_id"]]
        identity = story_identity(row)
        candidate_headline = headline(row, frontpage=True)
        if source.publisher_family in publishers or identity in identities or any(
            frontpage_match(candidate_headline, old) for old in headings
        ):
            continue
        picked.append({**public_article(row), "signal_type": rule[0], "signal_reason": rule[1]})
        publishers.add(source.publisher_family)
        identities.add(identity)
        headings.append(candidate_headline)
        if len(picked) == limit:
            break
    return {"articles": picked, "window_hours": 24, "generated_at": now.isoformat(),
            "basis": "Recent publisher titles and excerpts matched to explicit impact rules; not independent verification."}
