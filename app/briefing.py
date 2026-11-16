"""A bounded daily reading selection from attributed publisher records."""
from datetime import UTC, datetime, timedelta

from app.coverage import public_article
from app.intelligence import deduplicate
from app.sources import BY_ID
from app.story_coverage import compare_coverage, coverage_match, headline
from app.world_edition import diverse_stories

BRIEFING_COVERAGE = {"reporting", "publisher", "journal", "preprint", "advisory"}


def build_briefing(rows, *, hours=24, limit=5):
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=hours)
    eligible = []
    for row in rows:
        source = BY_ID.get(row.get("source_id"))
        try:
            published = datetime.fromisoformat(row["published_at"])
            if source and source.kind != "video" and source.coverage in BRIEFING_COVERAGE and cutoff <= published <= now:
                eligible.append(public_article(row))
        except (KeyError, TypeError, ValueError):
            continue
    pool = deduplicate(eligible)
    ordered = diverse_stories(pool, min(len(pool), limit * 3), lead_with_incident=True)
    selected, headlines = [], []
    for article in ordered:
        current = headline(article)
        if any(coverage_match(current, previous) for previous in headlines):
            continue
        matches = compare_coverage(article, pool)
        article["coverage_count"] = 1 + len(matches)
        article["coverage_publishers"] = [article["publisher"], *(row["publisher"] for row in matches)]
        selected.append(article)
        headlines.append(current)
        if len(selected) == limit:
            break
    return {"articles": selected, "hours": hours, "updated_at": now.isoformat(),
            "latest_published_at": max((row["published_at"] for row in pool), default=None),
            "publishers": len({row["publisher"] for row in pool}), "total_candidates": len(pool),
            "basis": "Recent publisher reporting, official updates and research, selected for topic and publisher diversity."}
