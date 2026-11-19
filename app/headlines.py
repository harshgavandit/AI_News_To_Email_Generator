"""Front-page selections from recent reporting and reviewed developing stories."""
from datetime import UTC, datetime, timedelta

from app.article_metadata import restore_metadata
from app.article_language import article_language
from app.coverage import public_article
from app.intelligence import story_identity
from app.selection import words
from app.sources import BY_ID
from app.story_coverage import coverage_match, headline
from app.news_signals import COMMERCE, news_score, impact_score

HEADLINE_HOURS = 72
DEVELOPING_CANDIDATE_LIMIT = 160
DEVELOPING_SOURCE_LIMIT = 5


def headline_score(article, now):
    return news_score(article, now), article["published_at"], article["id"]


def developing_coverage(rows, prepared):
    """Group recent matching reports without treating a shared company as the same event."""
    result, represented = [], []
    candidates = rows[:DEVELOPING_CANDIDATE_LIMIT]
    for anchor in candidates:
        current = prepared[anchor["id"]]
        if impact_score(anchor) < 10 or any(coverage_match(current, old) for old in represented):
            continue
        matches = [anchor, *(row for row in candidates if row["id"] != anchor["id"]
                             and coverage_match(current, prepared[row["id"]]))]
        publishers, links, matched_sources = set(), set(), []
        for row in matches:
            source = BY_ID[row["source_id"]]
            if source.publisher_family in publishers:
                continue
            identity = story_identity(restore_metadata(row))
            if identity in links:
                continue
            publishers.add(source.publisher_family)
            links.add(identity)
            matched_sources.append(row)
        if len(matched_sources) < 2:
            continue
        shown = [public_article(row) for row in matched_sources[:DEVELOPING_SOURCE_LIMIT]]
        public = shown[0]
        sources = [{"publisher": row["publisher"], "label": row["title"], "url": row["url"],
                    "article_id": row["id"], "published_at": row["published_at"],
                    "date_precision": row.get("publication_date_precision"),
                    "coverage": row["coverage"], "language": row["language"],
                    "publisher_family": row["publisher_family"], "excerpt": row["cleanSummary"]}
                   for row in shown]
        result.append({"id": anchor["id"], "article_id": anchor["id"], "title": anchor["title"],
            "topic": public["topic_label"],
            "summary": public["cleanSummary"], "updated_at": max(row["published_at"] for row in matches),
            "query": anchor["title"][:150], "sources": sources, "source_count": len(matched_sources),
            "source_count_basis": "distinct_publisher_families_in_sample", "basis": "matching_publisher_headlines"})
        represented.append(current)
        if len(result) == 2:
            break
    return result

def build_headlines(rows, *, now=None, limit=4):
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=HEADLINE_HOURS)
    eligible = []
    for article in rows:
        source = BY_ID.get(article.get("source_id"))
        if (not source or source.coverage not in {"reporting", "publisher", "advisory", "release"}
                or article.get("kind") not in {"news", "engineering", "video", "research"}
                or (source.kind in {"video", "research"} or source.coverage == "release") and impact_score(article) == 0
                or COMMERCE.search(article["title"])):
            continue
        if cutoff <= datetime.fromisoformat(article["published_at"]) <= now:
            eligible.append(article)

    eligible.sort(key=lambda article: headline_score(article, now), reverse=True)
    # Check a bounded shortlist so the first request after deployment never has to
    # reclassify the entire archive while the next scheduled ingest labels it.
    shortlist = eligible[:DEVELOPING_CANDIDATE_LIMIT]
    shortlist.sort(key=lambda article: article_language(restore_metadata(article)) == "en", reverse=True)
    eligible[:DEVELOPING_CANDIDATE_LIMIT] = shortlist
    prepared = {row["id"]: headline(row) for row in eligible[:DEVELOPING_CANDIDATE_LIMIT]}
    coverage = developing_coverage(eligible, prepared)
    picked, publishers, used_regions, used_topics, seen_titles = [], set(), set(), set(), []
    links, headlines = set(), []
    for unique_topic, unique_region in ((True, True), (False, True), (False, False)):
        for candidate in eligible:
            if candidate["publisher"] in publishers:
                continue
            if any(coverage_match(headline(candidate), prepared[item["id"]]) for item in coverage):
                continue
            article = public_article(candidate)
            region = article["region_id"]
            if (unique_topic and article["topic"] in used_topics) or (unique_region and region in used_regions):
                continue
            tokens = words(article["title"])
            if any(tokens and len(tokens & old) / len(tokens | old) >= .67 for old in seen_titles):
                continue
            identity = story_identity(article)
            candidate_headline = headline(article)
            if identity in links or any(coverage_match(candidate_headline, old) for old in headlines):
                continue
            picked.append(article)
            links.add(identity)
            headlines.append(candidate_headline)
            publishers.add(article["publisher"])
            used_topics.add(article["topic"])
            used_regions.add(region)
            seen_titles.append(tokens)
            if len(picked) == limit:
                return {"coverage": coverage, "articles": picked}
    return {"coverage": coverage, "articles": picked}
