"""One classification for API filters, archives, and global edition selection."""
from sqlalchemy import case, func, or_

from app.sources import BY_ID

TOPICS = {
    "outages": "Outages & service updates",
    "industry": "Industry & policy",
    "chips": "Chips & devices",
    "security": "Security & privacy",
    "software": "Software & cloud",
    "ai": "AI & research",
}

# Only reclassify general reporting; specialist feeds keep their own topic unless
# a headline clearly describes a service disruption.
OUTAGE_TERMS = ("outage", "service disruption", "service interruption", "services down", "services go down")
HEADLINE_RULES = {
    "security": ("data breach", "cyberattack", "cyber attack", "ransomware", "security flaw", "security update", "privacy"),
    "chips": ("nvidia", "semiconductor", "chipmaker", "chip maker", "qualcomm", "geforce", "radeon", "gpu", "iphone", "pixel phone", "galaxy phone"),
    "ai": (" ai ", "chatgpt", "openai", "anthropic", "deepmind", "large language model", "artificial intelligence"),
    "software": ("open source", "programming language", "linux kernel", "kubernetes", "developer tools", "postgresql"),
}


def topic_for(article):
    source = BY_ID.get(article.get("source_id") or article["source"])
    base = source.topic if source else "ai"
    text = f" {article['title'].lower()} "
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
        (reporting & matches(OUTAGE_TERMS), "outages"),
        *((general & matches(terms), topic) for topic, terms in HEADLINE_RULES.items()),
        *((source.in_([s.id for s in BY_ID.values() if s.topic == topic]), topic) for topic in TOPICS if topic != "ai"),
        else_="ai",
    )


def public_article(article):
    source = BY_ID.get(article.get("source_id") or article["source"])
    topic = topic_for(article)
    result = dict(article, topic=topic, coverage=source.coverage if source else "publisher",
                  region=source.region if source else "Global")
    if topic == "security":
        result["description"] = "See the source for affected products, impact, and updates."
    return result
