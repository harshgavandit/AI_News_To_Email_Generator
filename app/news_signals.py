"""Explainable editorial signals extracted from supplied publisher headlines."""
from datetime import UTC, datetime
import re

SIGNALS = (
    ("acquisition", "Acquisitions & mergers", 14, r"\b(?:acquir\w*|acquisition|merger|takeover|buyout)\b"),
    ("ipo", "IPOs & public markets", 13, r"\b(?:ipo|initial public offering|stock.market debut|go(?:es|ing)? public|prospectus)\b"),
    ("earnings", "Earnings & financial results", 12, r"\b(?:earnings|quarterly results|financial results|revenue (?:beat|miss|surge|growth)|results.*(?:nvidia|chipmaker))\b"),
    ("outage", "Service disruptions", 15, r"\b(?:outage|service disruption|unavailable|services? (?:is|are) down|service (?:restored|recovery))\b"),
    ("security", "Security incidents", 15, r"\b(?:breach|ransomware|zero.day|exploit(?:ed|s|ation)?|actively exploited|critical vulnerabilit\w*)\b"),
    ("policy", "Policy & governance", 12, r"\b(?:antitrust|export controls?|sanctions?|transparency initiative|regulat\w*|ai (?:safety|governance))\b"),
    ("launch", "Products & model releases", 10, r"\b(?:launch\w*|unveil\w*|introduc\w*|rolls? out|expands? access|now available|flagship|keynote|ignite\s+20\d{2}|(?:tasks|features?).*\bfree|linked billing)\b"),
    ("funding", "Funding & investment", 9, r"\b(?:raises?|funding|series [a-f]|seed round|venture capital)\b|\$[\d.]+[bm]\b"),
    ("leadership", "Company leadership", 12, r"\b(?:ceo|chief executive)\b.*\b(?:resign\w*|depart\w*|appoint\w*|successor|search|steps? down|transition)\b"),
)
COMPILED = tuple((key, label, weight, re.compile(pattern, re.I)) for key, label, weight, pattern in SIGNALS)
MATERIAL_TERMS = ("acquir", "acquisition", "ipo", "earnings", "outage", "breach", "launch", "unveil", "keynote", "transparency", "linked billing")
COMMERCE = re.compile(r"\b(?:black friday|coupons?|buying guide|best deals|prime day|hands.on review)\b", re.I)
TECH_ENTITIES = re.compile(
    r"\b(?:MongoDB|Firebolt|Databricks|Snowflake|Salesforce|Oracle|Cloudflare|GitHub|GitLab|"
    r"Gemini|Qwen(?:\d+(?:[.\w-]+)?)?|Claude|DeepSeek|Mistral|Qualcomm|Broadcom|ASML|"
    r"Palantir|ServiceNow|CrowdStrike|Palo Alto Networks|Perplexity|Cursor|Hugging Face)\b", re.I)


def story_signals(article):
    title = article.get("title", "")
    if COMMERCE.search(title):
        return []
    return [{"id": key, "label": label} for key, label, _, matcher in COMPILED if matcher.search(title)]


def impact_score(article):
    title = article.get("title", "")
    if COMMERCE.search(title):
        return -12
    return max((weight for _, _, weight, matcher in COMPILED if matcher.search(title)), default=0)


def news_score(article, now=None):
    now = now or datetime.now(UTC)
    try:
        published = datetime.fromisoformat(article.get("published_at") or article["publishedAt"])
        age = max(0, (now - published).total_seconds() / 3600)
    except (KeyError, TypeError, ValueError):
        return 0.0
    # Event importance decays along with recency, so old incidents cannot pin a lead indefinitely.
    return round(impact_score(article) / (1 + age / 36) + max(0, 24 - age / 2), 3)
