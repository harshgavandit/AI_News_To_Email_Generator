"""Explainable priority signals from recent source material, not verified breaking alerts."""
import re
from datetime import UTC, datetime, timedelta

from app.coverage import public_article
from app.intelligence import story_identity
from app.sources import BY_ID
from app.story_coverage import coverage_match, headline

RULES = (
    ("security", "Exploitation, breach or urgent security development", re.compile(
        r"\b(?:exploit(?:ed|s|ation)?|zero.day|ransomware|data breach|actively exploited|critical vulnerability)\b", re.I)),
    ("outage", "Service disruption", re.compile(r"\b(?:outage|service disruption|services? (?:is|are) down)\b", re.I)),
    ("industry", "Significant company or industry change", re.compile(
        r"\b(?:acqui(?:res|red|sition)|antitrust|export controls?|raises? \$|\$[\d.]+[bm]|ceo (?:resigns|steps down))\b", re.I)),
)


def priority_signals(rows, *, now=None, limit=6):
    now = now or datetime.now(UTC)
    candidates = []
    for row in rows:
        source = BY_ID.get(row.get("source_id"))
        if not source or source.coverage not in {"reporting", "advisory", "publisher"} or source.kind == "video":
            continue
        published = datetime.fromisoformat(row["published_at"])
        if not now - timedelta(hours=24) <= published <= now:
            continue
        material = row["title"] + " " + row.get("description", "")[:500]
        rule = next((rule for rule in RULES if rule[2].search(material)), None)
        if not rule:
            continue
        age = (now - published).total_seconds() / 3600
        score = 24 - age + (6 if source.coverage == "advisory" else 0)
        candidates.append((score, published, row["id"], rule, row))
    picked, identities, publishers, headings = [], set(), set(), []
    for _, _, _, rule, row in sorted(candidates, reverse=True):
        source = BY_ID[row["source_id"]]
        identity = story_identity(row)
        candidate_headline = headline(row)
        if source.group in publishers or identity in identities or any(
            coverage_match(candidate_headline, old) for old in headings
        ):
            continue
        picked.append({**public_article(row), "signal_type": rule[0], "signal_reason": rule[1]})
        publishers.add(source.group)
        identities.add(identity)
        headings.append(candidate_headline)
        if len(picked) == limit:
            break
    return {"articles": picked, "window_hours": 24, "generated_at": now.isoformat(),
            "basis": "Recent publisher titles and excerpts matched to explicit impact rules; not independent verification."}
