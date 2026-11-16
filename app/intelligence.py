"""Explainable discovery across news, practitioner articles and research.

Classification and ranking use source records, not invented article facts.
Personal preferences are supplied per request and are not stored as identities.
"""
from collections import Counter
from datetime import UTC, datetime, timedelta
import math
import re

from app.article_metadata import restore_metadata
from app.discovery import search_terms, search_text

SUBJECTS = {
    "programming": "Programming", "cloud": "Cloud & infrastructure", "open-source": "Open source",
    "funding": "Funding & venture capital", "acquisitions": "Mergers & acquisitions",
    "quantum": "Quantum computing", "robotics": "Robotics", "data": "Data & databases",
    "web": "Web development", "mobile": "Mobile technology", "space": "Space technology",
    "climate": "Climate & energy tech",
}
SUBJECT_PATTERNS = {
    "programming": r"programming|compilers?|python|javascript|typescript|golang|rust|coding|ruby|java|c\+\+|c#|cs\.pl",
    "cloud": r"cloud|aws|azure|kubernetes|serverless|devops|docker|containers?|infrastructure|distributed systems?",
    "open-source": r"open[ -]source|open[ -]weights?|linux|github|gitlab|free software|código (?:aberto|abierto)",
    "funding": r"funding|venture capital|seed round|series [a-f]|raises? \$|raised \$|levée de fonds|finanzierung",
    "acquisitions": r"acquir(?:e|es|ed|ing)|acquisitions?|mergers?|buyouts?|takeovers?",
    "quantum": r"quantum|qubit|quantique|quanten",
    "robotics": r"robotics|robots?|humanoids?|autonomous (?:vehicles?|drones?)|ロボット",
    "data": r"databases?|postgres(?:ql)?|sqlite|mysql|mongodb|redis|data engineering|data science|analytics|duckdb",
    "web": r"web development|frontend|front-end|react|next\.js|css|html|browsers?|webassembly|vue|svelte",
    "mobile": r"smartphones?|iphone|android|ios|mobile|wearables?",
    "space": r"spacex|satellites?|rockets?|spaceflight|orbital|starlink",
    "climate": r"climate tech|clean[ -]tech|renewable energy|battery|batteries|solar power|nuclear fusion|energy storage",
}
MATCHERS = {key: re.compile(rf"(?<!\w)(?:{value})(?!\w)", re.I) for key, value in SUBJECT_PATTERNS.items()}


def subjects_for(article):
    article = restore_metadata(article)
    text = " ".join(str(article.get(key) or "") for key in ("title", "description", "category"))
    text += " " + " ".join(article.get("tags", []))
    return [key for key, matcher in MATCHERS.items() if matcher.search(text)]


def deduplicate(articles):
    """Collapse exact canonical duplicates; keep different reporting on an event."""
    from app.news import canonical_url
    seen = set()
    result = []
    for raw in articles:
        article = restore_metadata(raw)
        try:
            link = article.get("original_url") or article.get("url") or ""
            identity = canonical_url(link)
        except ValueError:
            identity = article.get("id")
        if identity in seen:
            continue
        seen.add(identity)
        result.append(article)
    return result


def recommend(articles, *, topics=(), preferred_sources=(), subjects=(), authors=(), exclude_ids=(), query="", limit=24):
    from app.coverage import public_article
    now = datetime.now(UTC)
    excluded = set(exclude_ids)
    terms = search_terms(query)
    candidates = []
    for raw in articles:
        article = public_article(raw)
        if article["id"] in excluded:
            continue
        try:
            published = datetime.fromisoformat(article["published_at"])
            if not now - timedelta(days=30) <= published <= now:
                continue
        except (ValueError, TypeError):
            continue
        haystack = search_text(" ".join([article["title"], article["description"], article["publisher"],
                                        article.get("author", ""), *article.get("tags", [])]))
        if terms and not all(term in haystack for term in terms):
            continue
        age_hours = (now - published).total_seconds() / 3600
        score = 3 / (1 + age_hours / 24)
        reasons = []
        if article["author_key"] and article["author_key"] in authors:
            score += 7
            reasons.append("From an author you follow")
        if article["topic"] in topics:
            score += 5
            reasons.append(f"Matches {article['topic_label']}")
        matches = [SUBJECTS[key] for key in subjects if key in article["subjects"]]
        if matches:
            score += 4
            reasons.append("Matches " + ", ".join(matches[:2]))
        if article["source"] in preferred_sources or article.get("source_id") in preferred_sources:
            score += 4
            reasons.append("From a source you follow")
        if not reasons:
            reasons.append("Recent coverage to explore")
        if article["has_excerpt"]:
            score += .5
        # Engagement is a small, bounded signal, never a claim about accuracy.
        score += min(.75, math.log1p(article.get("points", 0)) / 10)
        article["recommendation_reasons"] = reasons
        candidates.append((score, article))
    candidates.sort(key=lambda pair: (pair[0], pair[1]["published_at"], pair[1]["id"]), reverse=True)
    pool = deduplicate([article for _, article in candidates])
    # Greedy diversity penalty allows more than one article from a publisher
    # without letting a prolific source dominate the first screen.
    scores = {article["id"]: score for score, article in candidates}
    counts = Counter()
    ranked = []
    while pool and len(ranked) < limit:
        best = max(range(len(pool)), key=lambda i: scores[pool[i]["id"]] - counts[pool[i]["source"]] * 2)
        article = pool.pop(best)
        ranked.append(article)
        counts[article["source"]] += 1
    return {"articles": ranked, "total_candidates": len(candidates), "updated_at": now.isoformat(),
            "personalized": bool(topics or preferred_sources or subjects or authors),
            "basis": "Selected interests, followed authors and publications; ranked by freshness with source diversity."}


def related_articles(article, candidates, limit=5):
    ranked = recommend(candidates, topics=[article["topic"]], subjects=article.get("subjects", []),
                       exclude_ids=[article["id"]], limit=limit + 5)["articles"]
    return [item for item in ranked if item["topic"] == article["topic"]
            or set(item["subjects"]) & set(article.get("subjects", []))][:limit]
