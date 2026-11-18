"""Front-page selections from recent reporting and reviewed developing stories."""
from datetime import UTC, datetime, timedelta

from app.coverage import public_article
from app.intelligence import story_identity
from app.selection import words
from app.sources import BY_ID
from app.story_coverage import coverage_match, headline
from app.news_signals import COMMERCE, news_score, impact_score

HEADLINE_HOURS = 72


def headline_score(article, now):
    return news_score(article, now), article["published_at"], article["id"]


def developing_coverage(rows, prepared):
    """Group recent matching reports without treating a shared company as the same event."""
    result, represented = [], []
    for anchor in rows[:160]:
        current = prepared[anchor["id"]]
        if impact_score(anchor) < 10 or any(coverage_match(current, old) for old in represented):
            continue
        matches = [anchor, *(row for row in rows[:160] if row["id"] != anchor["id"]
                             and coverage_match(current, prepared[row["id"]]))]
        publishers, sources = set(), []
        for row in matches:
            source = BY_ID[row["source_id"]]
            if source.publisher_family in publishers:
                continue
            sources.append({"publisher": row["publisher"], "label": row["title"], "url": row["url"]})
            publishers.add(source.publisher_family)
            if len(sources) == 5:
                break
        if len(sources) < 2:
            continue
        public = public_article(anchor)
        result.append({"id": anchor["id"], "title": anchor["title"], "topic": public["topic_label"],
            "summary": public["cleanSummary"], "updated_at": max(row["published_at"] for row in matches),
            "query": anchor["title"][:150], "sources": sources, "basis": "matching_publisher_headlines"})
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
    prepared = {row["id"]: headline(row) for row in eligible[:160]}
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
