"""Assemble a fast, source-linked edition without requiring a model call."""
import re
from datetime import UTC, datetime

from app.coverage import TOPICS, public_article, region_id
from app.intelligence import story_identity
from app.selection import words
from app.sources import BY_ID
from app.news_signals import news_score
from app.web_digest import digest_markdown, safe_email_html

PROVIDERS = {
    "microsoft-365": r"\b(microsoft 365|m365|outlook|exchange online|microsoft outage|microsoft teams)\b",
    "azure": r"\bazure\b",
    "aws": r"\b(aws|amazon web services)\b",
    "google-cloud": r"\bgoogle cloud\b",
    "github": r"\bgithub\b",
    "cloudflare": r"\bcloudflare\b",
}
SCHEDULED_WORK = re.compile(r"\b(?:scheduled|planned) (?:maintenance|work)\b", re.I)
REPORTING_PRIORITY = {"reporting": 2, "publisher": 1, "preprint": 1, "journal": 1, "advisory": 1}


def incident_key(article):
    if article["topic"] != "outages":
        return None
    return next((name for name, pattern in PROVIDERS.items() if re.search(pattern, article["title"], re.I)), None)


def edition_candidate(article):
    return article["coverage"] != "status" or not SCHEDULED_WORK.search(article["title"])


def diverse_stories(candidates, count, *, previous=(), lead_with_incident=False):
    picked = []
    ids = {story["id"] for story in previous}
    links = {story_identity(story) for story in previous}
    topics = {story["topic"] for story in previous}
    regions = {region_id(story["region"]) for story in previous}
    publishers = {story["publisher"] for story in previous}
    incidents = {key for story in previous if (key := incident_key(story))}
    seen_titles = [words(story["title"]) for story in previous]
    pool = [(story, incident_key(story), words(story["title"]), story_identity(story)) for story in candidates
            if story["id"] not in ids and edition_candidate(story)]
    now = datetime.now(UTC)

    def priority(row):
        story, _, _, _ = row
        reported_outage = (
            lead_with_incident and not picked and story["topic"] == "outages" and story["coverage"] == "reporting"
            and 0 <= (now - datetime.fromisoformat(story["published_at"])).total_seconds() <= 86400
        )
        new_region = region_id(story["region"]) not in regions
        new_topic = story["topic"] not in topics
        return (reported_outage, story["coverage"] != "article", story["publisher"] not in publishers,
                int(news_score(story, now) // 8), new_topic + new_region, new_region,
                REPORTING_PRIORITY.get(story["coverage"], 0), story["published_at"], story["id"])

    def is_duplicate(row):
        story, incident, tokens, identity = row
        return story["id"] in ids or identity in links or incident in incidents or any(
            tokens and old and len(tokens & old) / len(tokens | old) >= .72 for old in seen_titles
        )

    while pool and len(picked) < count:
        pool = [row for row in pool if not is_duplicate(row)]
        if not pool:
            break
        story, incident, tokens, identity = max(pool, key=priority)
        picked.append(story)
        ids.add(story["id"])
        links.add(identity)
        topics.add(story["topic"])
        regions.add(region_id(story["region"]))
        publishers.add(story["publisher"])
        if incident:
            incidents.add(incident)
        seen_titles.append(tokens)
    return picked


def select_world(articles, count, sources):
    allowed = set(sources)
    candidates = []
    for article in articles:
        source = BY_ID.get(article.get("source_id"))
        if allowed.intersection((article["source"], article.get("source_id"), source.group if source else None)):
            candidates.append(public_article(article))
    return diverse_stories(candidates, count, lead_with_incident=True)


def build_world(articles, hours, all_pool=None, *, scope=(), includes_pins=False):
    window = {24: "24 hours", 168: "7 days", 720: "30 days"}.get(hours, f"{hours} hours")
    scope_text = f" Archive filters include {', '.join(scope)}." if scope else ""
    pinned_text = " Pinned stories may be outside these filters." if includes_pins else ""
    intro = {
        "greeting": "Your global technology brief",
        "introduction": f"The archive window covers the past {window}.{scope_text}{pinned_text} "
                        "Story labels identify publisher excerpts and headline-only entries.",
    }
    result = {
        "edition": "world",
        "introduction": intro,
        "articles": [],
        "generated_at": datetime.now(UTC).isoformat(),
        "quick_hits": [],
        "scope": list(scope),
    }
    if all_pool:
        quick_candidates = diverse_stories((public_article(item) for item in all_pool), 3, previous=articles)
        result["quick_hits"] = [
            {
                "title": q["title"],
                "url": q["url"],
                "publisher": q.get("publisher", ""),
                "region": q.get("region", "Global"),
                "region_id": q["region_id"],
                "topic": q["topic"],
            }
            for q in quick_candidates
        ]

    for rank, item in enumerate(articles, start=1):
        excerpt = (item.get("cleanSummary") or item.get("description", "")) if item.get("has_excerpt", True) else ""
        excerpt = (excerpt[:480].rsplit(" ", 1)[0] + "…") if len(excerpt) > 480 else excerpt
        label = TOPICS.get(item["topic"], item["topic"].title())
        
        art_entry = {
            "digest_id": item["id"],
            "rank": rank,
            "title": item["title"],
            "summary": excerpt or "Read the original source for details.",
            "summary_basis": "publisher_excerpt" if excerpt else "headline_only",
            "url": item["url"],
            "article_type": item["source"],
            "publisher": item["publisher"],
            "author": item.get("author", ""),
            "topic": item["topic"],
            "topic_label": label,
            "published_at": item["published_at"],
            "coverage": item["coverage"],
            "region": item["region"],
            "region_id": item["region_id"],
            "language": item["language"],
            "keyTakeaway": item.get("keyTakeaway", ""),
            "whyItMatters": item.get("whyItMatters", ""),
        }
        if research_status := item.get("research_status"):
            art_entry["research_status"] = research_status
        result["articles"].append(art_entry)
        
    result["markdown"] = digest_markdown(result)
    result["html"] = safe_email_html(result)
    return result
