"""Explainable discovery across news, practitioner articles and research.

Classification and ranking use source records, not invented article facts.
Personal preferences are supplied per request and are not stored as identities.
"""
from collections import Counter
from datetime import UTC, datetime, timedelta
import math
import re

from app.article_metadata import restore_metadata
from app.discovery import relevance_score, search_terms, search_text

SUBJECTS = {
    "agents": "AI agents & orchestration", "llms": "LLMs & inference", "generative-ai": "Generative AI",
    "machine-learning": "Machine learning & MLOps", "devops": "DevOps & reliability",
    "programming": "Programming", "cloud": "Cloud & infrastructure", "open-source": "Open source",
    "funding": "Funding & venture capital", "acquisitions": "Mergers & acquisitions",
    "quantum": "Quantum computing", "robotics": "Robotics", "data": "Data & databases",
    "web": "Web development", "mobile": "Mobile technology", "space": "Space technology",
    "climate": "Climate & energy tech",
}
SUBJECT_PATTERNS = {
    "agents": r"agentic|ai agents?|multi[ -]agent|langgraph|crewai|autogen|agent orchestration|model context protocol|mcp",
    "llms": r"llms?|large language models?|inference|vllm|llama\.cpp|sglang|tokenization|fine[ -]tuning|quantization",
    "generative-ai": r"generative ai|genai|diffusion models?|text[ -]to[ -](?:image|video)|image generation|multimodal",
    "machine-learning": r"machine learning|mlops|pytorch|tensorflow|scikit-learn|model training|neural networks?|feature stores?",
    "devops": r"devops|site reliability|sre|ci/cd|observability|opentelemetry|terraform|opentofu|platform engineering|gitops",
    "programming": r"programming|compilers?|python|javascript|typescript|golang|rust|coding|ruby|java|c\+\+|c#|cs\.pl",
    "cloud": r"cloud|aws|azure|kubernetes|serverless|devops|docker|containers?|infrastructure|distributed systems?",
    "open-source": r"open[ -]source|open[ -]weights?|linux|github|gitlab|free software|código (?:aberto|abierto)",
    "funding": r"funding|venture capital|seed round|series [a-f]|raises? \$|raised \$|levée de fonds|finanzierung|ronda de financiación|جولة تمويل",
    "acquisitions": r"acquir(?:e|es|ed|ing)|acquisitions?|mergers?|buyouts?|takeovers?|fusiones|استحواذ",
    "quantum": r"quantum|qubit|quantique|quanten",
    "robotics": r"robotics|robots?|humanoids?|autonomous (?:vehicles?|drones?)|ロボット",
    "data": r"databases?|postgres(?:ql)?|sqlite|mysql|mongodb|redis|data engineering|data science|analytics|duckdb",
    "web": r"web development|frontend|front-end|react|next\.js|css|html|browsers?|webassembly|vue|svelte",
    "mobile": r"smartphones?|iphone|android|ios|mobile|wearables?",
    "space": r"spacex|satellites?|rockets?|spaceflight|orbital|starlink",
    "climate": r"climate tech|clean[ -]tech|renewable energy|battery|batteries|solar power|nuclear fusion|energy storage",
}
MATCHERS = {key: re.compile(rf"(?<!\w)(?:{value})(?!\w)", re.I) for key, value in SUBJECT_PATTERNS.items()}
REFERENCE = re.compile(r"\b(?:CVE-\d{4}-\d{4,}|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})\b", re.I)
GENERIC_TERMS = frozenset(
    "about after analysis and are article available because before been best both build can cloud developer explains "
    "first for from guide had has have how into its just latest learn makes may more news now one only our release "
    "report research says should software some startup technology than that the their them these they this through "
    "tools tutorial under update use using via was were what when where which who will with would you your".split()
)


def subjects_for(article):
    article = restore_metadata(article)
    text = " ".join(str(article.get(key) or "") for key in ("title", "description", "category"))
    text += " " + " ".join(article.get("tags", []))
    return [key for key, matcher in MATCHERS.items() if matcher.search(text)]


def story_identity(article):
    from app.news import canonical_url
    from urllib.parse import urlsplit

    link = article.get("original_url") or article.get("url") or ""
    try:
        canonical = canonical_url(link)
    except ValueError:
        return ("id", article.get("id"))
    parts = urlsplit(canonical)
    if parts.hostname in {"arxiv.org", "www.arxiv.org"}:
        paper = re.fullmatch(r"/(?:abs|pdf)/((?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7}))(?:v\d+)?(?:\.pdf)?", parts.path)
        if paper:
            return ("arxiv", paper.group(1))
    return ("url", canonical)


def deduplicate(articles):
    """Collapse canonical copies and alternate preprint links."""
    seen = set()
    result = []
    for raw in articles:
        article = restore_metadata(raw)
        identity = story_identity(article)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(article)
    return result


def recommend(articles, *, topics=(), preferred_sources=(), subjects=(), authors=(), exclude_ids=(), query="", limit=24,
              hours=720):
    from app.coverage import public_article
    now = datetime.now(UTC)
    earliest = now - timedelta(hours=hours)
    excluded = set(exclude_ids)
    phrase = search_text(query)
    terms = search_terms(phrase)
    candidates = []
    for raw in articles:
        article = public_article(raw)
        if article["id"] in excluded:
            continue
        try:
            published = datetime.fromisoformat(article["published_at"])
            if not earliest <= published <= now:
                continue
        except (ValueError, TypeError):
            continue
        match = relevance_score(article, phrase, terms) if terms else 0
        if match is None:
            continue
        age_hours = (now - published).total_seconds() / 3600
        score = 3 / (1 + age_hours / 24) + match / 4
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


def references(article):
    text = f"{article['title']} {article.get('description', '')}"
    return {match.upper() for match in REFERENCE.findall(text)}


def related_terms(article):
    title_terms = [term for term in search_terms(article["title"])
                   if len(term) >= 3 and not term.isdigit() and term not in GENERIC_TERMS]
    return (*sorted(search_text(ref) for ref in references(article))[:3], *title_terms[:8])


def related_articles(article, candidates, limit=5):
    """Rank by shared identifiers or distinct headline terms, with source diversity."""
    ref_ids = references(article)
    anchor_title = set(related_terms(article))
    ranked = []
    now = datetime.now(UTC)
    for raw in candidates:
        try:
            if not now - timedelta(days=30) <= datetime.fromisoformat(raw["published_at"]) <= now:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        if raw["id"] == article["id"]:
            continue
        raw = restore_metadata(raw)
        item_refs = ref_ids & references(raw)
        candidate_terms = set(related_terms(raw))
        overlap = anchor_title & candidate_terms
        confidence = 2 * len(overlap) / max(1, len(anchor_title) + len(candidate_terms))
        if not item_refs and (len(overlap) < 2 or confidence < .25):
            continue
        ranked.append((len(item_refs), confidence, raw.get("source") != article["source"],
                       raw["published_at"], raw["id"], raw, item_refs, overlap))
    ranked.sort(key=lambda item: item[:5], reverse=True)
    selected, identities, publishers = [], {story_identity(article)}, Counter()
    for _, _, _, _, _, raw, item_refs, overlap in ranked:
        identity = story_identity(raw)
        if identity in identities or publishers[raw["source"]] >= 2:
            continue
        reason = ("Shared reference " + sorted(item_refs)[0] if item_refs else
                  "Shared headline terms: " + ", ".join(sorted(overlap)[:3]))
        selected.append(dict(raw, related_reason=reason))
        identities.add(identity)
        publishers[raw["source"]] += 1
        if len(selected) >= limit:
            break
    return selected
