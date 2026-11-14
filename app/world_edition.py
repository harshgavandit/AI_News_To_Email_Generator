"""Assemble a fast, source-linked edition without requiring a model call."""
import re
from datetime import UTC, datetime

from app.coverage import TOPICS, public_article
from app.selection import words
from app.sources import BY_ID
from app.web_digest import safe_email_html

PROVIDERS = {
    "microsoft-365": r"\b(microsoft 365|m365|outlook|exchange online|microsoft outage|microsoft teams)\b",
    "azure": r"\bazure\b",
    "aws": r"\b(aws|amazon web services)\b",
    "google-cloud": r"\bgoogle cloud\b",
    "github": r"\bgithub\b",
    "cloudflare": r"\bcloudflare\b",
}


def incident_key(article):
    if article["topic"] != "outages":
        return None
    return next((name for name, pattern in PROVIDERS.items() if re.search(pattern, article["title"], re.I)), None)


def select_world(articles, count, sources):
    allowed = set(sources)
    candidates = []
    for article in articles:
        source = BY_ID.get(article.get("source_id"))
        if allowed.intersection((article["source"], article.get("source_id"), source.group if source else None)):
            candidates.append(public_article(article))
    candidates = [a for a in candidates if a["coverage"] != "status" or not re.search(
        r"\b(maintenance|scheduled work)\b", a["title"], re.I)]
    candidates.sort(key=lambda a: (a["published_at"], a["id"]), reverse=True)
    # Lead with an independently covered outage when it is current enough to lead.
    incidents = [a for a in candidates if a["topic"] == "outages" and a["coverage"] == "reporting"
                 and (datetime.now(UTC) - datetime.fromisoformat(a["published_at"])).total_seconds() <= 86400]
    remaining = [a for a in candidates if a["coverage"] == "reporting"]
    pool = {a["id"]: a for a in [*incidents, *remaining, *candidates]}
    picked, topics, publishers, incident_keys, seen = [], set(), set(), set(), []
    for diverse in (True, False):
        for a in pool.values():
            topic, publisher, key, tokens = a["topic"], a["publisher"], incident_key(a), words(a["title"])
            if a in picked or (diverse and (topic in topics or publisher in publishers)):
                continue
            if (key and key in incident_keys) or any(tokens and old and
                    len(tokens & old) / len(tokens | old) >= .72 for old in seen):
                continue
            picked.append(a)
            topics.add(topic)
            publishers.add(publisher)
            incident_keys.add(key)
            seen.append(tokens)
            if len(picked) == count:
                return picked
    return picked


def build_world(articles, hours, all_pool=None):
    window = {24: "24 hours", 168: "7 days", 720: "30 days"}.get(hours, f"{hours} hours")
    intro = {
        "greeting": "Your global brief from Informa AI",
        "introduction": f"Recent stories across tech from the past {window}. Excerpts come from the linked publishers; check provider status pages for current incident details.",
    }
    result = {
        "edition": "world",
        "introduction": intro,
        "articles": [],
        "generated_at": datetime.now(UTC).isoformat(),
        "quick_hits": [],
    }
    markdown = [f"# {intro['greeting']}", intro["introduction"]]

    if all_pool:
        picked_ids = {item["id"] for item in articles}
        picked_incidents = {key for item in articles if (key := incident_key(item))}
        quick_candidates = []
        for item in sorted(all_pool, key=lambda a: (a["published_at"], a["id"]), reverse=True):
            if item["id"] in picked_ids:
                continue
            story = public_article(item)
            key = incident_key(story)
            if key in picked_incidents or (story["coverage"] == "status" and re.search(
                    r"\b(maintenance|scheduled work)\b", story["title"], re.I)):
                continue
            quick_candidates.append(story)
            if key:
                picked_incidents.add(key)
            if len(quick_candidates) == 3:
                break
        result["quick_hits"] = [
            {
                "title": q["title"],
                "url": q["url"],
                "publisher": q.get("publisher", ""),
                "region": q.get("region", "Global"),
            }
            for q in quick_candidates
        ]

    for rank, item in enumerate(articles, start=1):
        excerpt = item.get("cleanSummary") or item.get("description", "")
        excerpt = (excerpt[:480].rsplit(" ", 1)[0] + "…") if len(excerpt) > 480 else excerpt
        label = TOPICS.get(item["topic"], item["topic"].title())
        takeaway = item.get("keyTakeaway") or item.get("whyItMatters", "")
        
        art_entry = {
            "digest_id": item["id"],
            "rank": rank,
            "title": item["title"],
            "summary": excerpt or "Read the original source for details.",
            "url": item["url"],
            "article_type": item["source"],
            "publisher": item["publisher"],
            "topic": item["topic"],
            "topic_label": label,
            "published_at": item["published_at"],
            "coverage": item["coverage"],
            "region": item["region"],
            "keyTakeaway": takeaway,
            "whyItMatters": item.get("whyItMatters", ""),
        }
        result["articles"].append(art_entry)
        
        md_part = f"## {rank}. {item['title']}\n{item['publisher']} · {label} · {item['published_at']}\n\n{art_entry['summary']}\n"
        if takeaway:
            md_part += f"\n* **Key Takeaway:** {takeaway}\n"
        md_part += f"\nSource: {item['url']}"
        markdown.append(md_part)

    if result["quick_hits"]:
        markdown.append("### Quick Hits Around the World")
        for qh in result["quick_hits"]:
            markdown.append(f"- [{qh['title']}]({qh['url']}) — {qh['publisher']} ({qh['region']})")

    result["markdown"] = "\n\n".join(markdown)
    result["html"] = safe_email_html(result)
    return result
