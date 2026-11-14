"""One classification for API filters, archives, and global edition selection."""
from sqlalchemy import case, func, or_

from app.sources import BY_ID
from app.sanitation import sanitize_article, sanitize_story_excerpt

TOPICS = {
    "ai": "AI & LLMs",
    "software": "Engineering & Dev",
    "startups": "Startups & Venture",
    "bigtech": "Big Tech",
    "industry": "Industry & Policy",
    "video": "Video Briefs",
    "chips": "Chips & Hardware",
    "security": "Security & Privacy",
    "outages": "Outages & Service Updates",
}

# Only reclassify general reporting; specialist feeds keep their own topic unless
# a headline clearly describes a service disruption.
OUTAGE_TERMS = ("outage", "service disruption", "service interruption", "services down", "services go down")
HEADLINE_RULES = {
    "startups": ("startup", "start-up", "funding", "series a", "series b", "series c", "seed round", "venture capital", "unicorn", "acquisition"),
    "bigtech": ("antitrust", "alphabet", "big tech", "doj", "ftc", "apple app store", "google monopoly"),
    "security": ("data breach", "cyberattack", "cyber attack", "ransomware", "security flaw", "zero-day", "vulnerability", "security update", "privacy"),
    "chips": ("nvidia", "semiconductor", "chipmaker", "chip maker", "qualcomm", "geforce", "radeon", "gpu", "tsmc", "arm chip", "blackwell", "h100"),
    "ai": (" ai ", "chatgpt", "openai", "anthropic", "claude", "deepmind", "large language model", "artificial intelligence", "llm", "agent", "transformer", "diffusion model", "gemini"),
    "software": ("open source", "programming language", "linux kernel", "kubernetes", "developer tools", "postgresql", "fastapi", "react", "compiler", "rust"),
}

WHY_IT_MATTERS_BY_TOPIC = {
    "ai": "Signals major progress in frontier model architecture, inference efficiency, and real-world agentic deployment.",
    "software": "Directly impacts cloud architecture patterns, engineering team velocity, and modern developer infrastructure.",
    "startups": "Highlights shifts in venture capital deployment, founder execution, and emerging product-market fit.",
    "bigtech": "Reflects platform power dynamics, antitrust regulatory pressure, and ecosystem moat transitions.",
    "chips": "Drives the foundational hardware economics and high-performance computing capacity underpinning global tech.",
    "security": "Affects critical enterprise risk posture, vulnerability patching urgency, and data governance standards.",
    "outages": "Directly influences mission-critical SLA resilience, failover engineering, and platform uptime.",
    "video": "Offers hands-on technical walkthroughs, system design analysis, and practitioner perspectives.",
    "industry": "Shapes policy frameworks, cross-border technology adoption, and macroeconomic headwinds.",
}


def topic_for(article):
    source = BY_ID.get(article.get("source_id") or article.get("source"))
    base = source.topic if source else "ai"
    if article.get("kind") == "video":
        return "video"
    text = f" {article.get('title', '').lower()} "
    if base == "outages" or ((base == "industry" or source and source.coverage == "reporting")
                             and any(term in text for term in OUTAGE_TERMS)):
        return "outages"
    if base == "industry":
        for topic, terms in HEADLINE_RULES.items():
            if any(term in text for term in terms):
                return topic
    return base


def topic_expression(columns):
    source = columns.source_id
    title = " " + func.lower(columns.title) + " "
    reporting = source.in_([s.id for s in BY_ID.values() if s.coverage == "reporting"])
    general = source.in_([s.id for s in BY_ID.values() if s.topic == "industry"])

    def matches(terms):
        return or_(*(title.contains(term, autoescape=True) for term in terms))

    return case(
        (columns.kind == "video", "video"),
        (reporting & matches(OUTAGE_TERMS), "outages"),
        *((general & matches(terms), topic) for topic, terms in HEADLINE_RULES.items()),
        *((source.in_([s.id for s in BY_ID.values() if s.topic == topic]), topic) for topic in TOPICS if topic != "ai"),
        else_="ai",
    )


def generate_why_it_matters(article, topic):
    custom = article.get("whyItMatters")
    if custom and len(custom.strip()) > 10:
        return custom.strip()
    return WHY_IT_MATTERS_BY_TOPIC.get(topic, WHY_IT_MATTERS_BY_TOPIC["ai"])


def public_article(article):
    article = sanitize_article(article)
    source = BY_ID.get(article.get("source_id") or article.get("source"))
    topic = topic_for(article)
    publisher = article.get("publisher") or (source.label if source else "")
    region = article.get("region") or (source.region if source else "Global")
    url = article.get("url", "")
    published_at = article.get("published_at", "")
    
    raw_summary = article.get("cleanSummary") or article.get("description") or article.get("summary") or ""
    clean_summary = sanitize_story_excerpt(raw_summary, article.get("source", ""), article.get("title", ""),
                                           channel=publisher) or "Read the original source for details."
    if topic == "security":
        clean_summary = "See the source for affected products, impact, and security mitigation advisories."
    
    why_it_matters = generate_why_it_matters(article, topic)
    words_count = len(clean_summary.split())
    reading_time = max(1, (words_count + 199) // 200)

    result = dict(article)
    result.update({
        # Strict requested schema: { id, title, cleanSummary, whyItMatters, category, region, sourceName, sourceUrl, publishedAt, readingTimeMinutes }
        "id": article.get("id", ""),
        "title": article.get("title", ""),
        "cleanSummary": clean_summary,
        "whyItMatters": why_it_matters,
        "category": topic,
        "region": region,
        "sourceName": publisher,
        "sourceUrl": url,
        "publishedAt": published_at,
        "readingTimeMinutes": reading_time,
        # Backward compatibility properties:
        "description": clean_summary,
        "summary": clean_summary,
        "topic": topic,
        "topic_label": TOPICS.get(topic, topic.title()),
        "publisher": publisher,
        "url": url,
        "published_at": published_at,
        "coverage": source.coverage if source else "reporting",
    })
    return result


REGIONS = {"APAC": {"Asia", "India", "APAC"}, "EU": {"Europe", "EU"}, "Global": {"Global"}}


def region_matches(article, region):
    source = BY_ID.get(article.get("source_id") or article.get("source"))
    actual = source.region if source else "Global"
    return region in ("", "all") or actual in REGIONS.get(region, {region})
