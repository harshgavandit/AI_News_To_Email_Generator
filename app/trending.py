"""Extract trending technology topics, companies, and keywords from recent reporting."""
from datetime import UTC, datetime, timedelta
import re
from collections import Counter, defaultdict
from app.discovery import search_text
from app.intelligence import deduplicate, references


TRENDING_PATTERNS = (
    ("OpenAI", "ai", r"\bopenai\b|chatgpt"),
    ("NVIDIA", "chips", r"\bnvidia\b|geforce|blackwell|hopper"),
    ("Anthropic", "ai", r"\banthropic\b|claude"),
    ("DeepSeek", "ai", r"\bdeepseek\b"),
    ("Google DeepMind", "ai", r"\bdeepmind\b|gemini"),
    ("Zero-Day & Exploits", "security", r"\bzero[ -]day|0[ -]day|cve-\d{4}"),
    ("Ransomware & Breaches", "security", r"\bransomware\b|data breach"),
    ("Kubernetes & Cloud", "software", r"\bkubernetes\b|k8s|cloud[- ]native"),
    ("PostgreSQL & Databases", "software", r"\bpostgresql\b|postgres|vector db|sqlite"),
    ("Rust & Systems", "software", r"\brust\b(?:\s+(?:compiler|code|crate|foundation|memory))?"),
    ("Linux & Open Source", "software", r"\blinux\b|open[ -]source"),
    ("Semiconductors & TSMC", "chips", r"\btsmc\b|foundr(?:y|ies)|lithography|semiconductor"),
    ("Venture & Funding", "startups", r"\bseries [a-e]\b|funding round|seed round|venture capital"),
    ("Mergers & Acquisitions", "startups", r"\bacqui(?:res|red|sition)\b|\bmergers?\b"),
    ("Robotics", "research", r"\brobotics\b|\bhumanoid robots?\b"),
    ("Space Technology", "industry", r"\bsatellites?\b|\bspaceflight\b|\bspacex\b"),
    ("Y Combinator", "startups", r"\by combinator\b|\byc\b"),
    ("Quantum Computing", "research", r"\bquantum\b"),
    ("Apple", "bigtech", r"\bapple\b|iphone|macbook"),
    ("Microsoft", "bigtech", r"\bmicrosoft\b|copilot|azure"),
    ("Meta AI", "ai", r"\bmeta ai\b|llama"),
    ("DevOps & Containers", "software", r"\bdocker\b|containers?|ci/cd"),
    ("Agents & Tooling", "ai", r"\bagentic\b|ai agents?|tool[ -]use|mcp\b"),
)


def extract_trending(articles, *, hours=48, limit=10):
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=hours)
    pool = []
    for a in articles:
        try:
            pub = datetime.fromisoformat(a["published_at"])
            if cutoff <= pub <= now:
                pool.append(a)
        except (ValueError, KeyError, TypeError):
            continue
    pool = deduplicate(pool)

    results = []
    for label, category, pattern in TRENDING_PATTERNS:
        matcher = re.compile(pattern, re.I)
        matched = [(a, matcher.search(" ".join([a.get("title", ""), a.get("cleanSummary") or a.get("description") or ""])))
                   for a in pool]
        matches = [(a, match) for a, match in matched if match]
        # Use a term that actually occurs in the source text. Editorial labels
        # such as "Venture & Funding" are not themselves searchable phrases.
        queries = Counter(search_text(match[0]) for _, match in matches)
        query = queries.most_common(1)[0][0] if queries else ""
        matching = [a for a, _ in matches if all(term in search_text(
            f"{a.get('title', '')} {a.get('description', '')}") for term in query.split())]
        count = len(matching)
        if count > 0:
            results.append({
                "tag": label,
                "category": category,
                "count": count,
                "query": query,
                "source_count": len({a.get("source_id") or a.get("source") for a in matching}),
            })

    advisory_mentions = defaultdict(list)
    for article in pool:
        for identifier in references(article):
            advisory_mentions[identifier].append(article)
    for identifier, mentions in advisory_mentions.items():
        publishers = {item.get("source") for item in mentions if item.get("source")}
        if len(publishers) < 2:
            continue
        results.append({"tag": identifier, "category": "security", "count": len(mentions),
                        "query": search_text(identifier), "source_count": len(publishers)})
    results.sort(key=lambda t: (t["count"], t["source_count"]), reverse=True)
    return {
        "trending": results[:limit],
        "total_analyzed": len(pool),
        "updated_at": now.isoformat(),
    }
