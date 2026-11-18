"""Extract trending technology topics, companies, and keywords from recent reporting."""
from datetime import UTC, datetime, timedelta
import re
from collections import Counter, defaultdict
from app.coverage import topic_for
from app.discovery import search_text
from app.intelligence import GENERIC_TERMS, deduplicate, references
from app.sources import BY_ID


def publisher_family(article):
    source = BY_ID.get(article.get("source_id"))
    return source.publisher_family if source else article.get("source") or article.get("source_id")


TRENDING_PATTERNS = (
    ("MongoDB & Analytics", "software", r"\bmongodb\b|\bfirebolt\b|\bdatabricks\b|\bsnowflake\b"),
    ("IPOs & Public Markets", "startups", r"\bipo\b|\binitial public offering\b|\bprospectus\b"),
    ("Earnings & Results", "bigtech", r"\bearnings\b|\bquarterly results\b|\bfinancial results\b"),
    ("Qwen & Alibaba AI", "ai", r"\bqwen[\w.-]*\b|\balibaba\b"),
    ("Microsoft Ignite", "bigtech", r"\bignite\b"),
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
COMPILED_PATTERNS = [(label, category, re.compile(pattern, re.I))
                     for label, category, pattern in TRENDING_PATTERNS]
GENERIC_TAGS = GENERIC_TERMS | {"ai", "dev", "programming", "webdev", "beginners", "discuss", "career",
                               "tech", "news", "tutorials", "community", "articles", "developer tools"}


def extract_trending(articles, *, hours=48, limit=10):
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=hours)
    midpoint = now - timedelta(hours=hours / 2)
    pool = []
    for a in articles:
        try:
            pub = datetime.fromisoformat(a["published_at"])
            if cutoff <= pub <= now:
                pool.append(a)
        except (ValueError, KeyError, TypeError):
            continue
    pool = deduplicate(pool)
    newest_ids = {article["id"] for article in pool if datetime.fromisoformat(article["published_at"]) > midpoint}

    def momentum(matching):
        recent = {publisher_family(row) for row in matching if row["id"] in newest_ids}
        previous = {publisher_family(row) for row in matching if row["id"] not in newest_ids}
        recent.discard(None)
        previous.discard(None)
        rise = len(recent) - len(previous)
        return {"recent_source_count": len(recent), "previous_source_count": len(previous),
                "momentum": "rising" if len(recent) >= 3 and rise >= 2 and len(recent) * 2 >= len(previous) * 3 else "steady"}

    results = []
    curated_tags = set()
    for label, category, matcher in COMPILED_PATTERNS:
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
            curated_tags.update(queries)
            results.append({
                "tag": label,
                "category": category,
                "count": count,
                "query": query,
                "source_count": len({publisher_family(a) for a in matching}),
                "basis": "recent_mentions",
                **momentum(matching),
            })

    advisory_mentions = defaultdict(list)
    for article in pool:
        for identifier in references(article):
            advisory_mentions[identifier].append(article)
    for identifier, mentions in advisory_mentions.items():
        publishers = {publisher_family(item) for item in mentions if publisher_family(item)}
        if len(publishers) < 2:
            continue
        results.append({"tag": identifier, "category": "security", "count": len(mentions),
                        "query": search_text(identifier), "source_count": len(publishers), "basis": "shared_advisory",
                        **momentum(mentions)})

    observed = defaultdict(list)
    for article in pool:
        # Archive and API feeds expose these tags through the same search document as the headline.
        tags = {search_text(tag) for tag in article.get("tags", ())}
        for tag in sorted(tags - GENERIC_TAGS - curated_tags):
            if 3 <= len(tag) <= 40 and len(tag.split()) <= 4 and any(char.isalpha() for char in tag):
                observed[tag].append(article)
    for tag, mentions in observed.items():
        publishers = {publisher_family(article) for article in mentions if publisher_family(article)}
        if len(publishers) >= 3:
            category = Counter(topic_for(article) for article in mentions).most_common(1)[0][0]
            results.append({"tag": tag, "category": category, "count": len(mentions), "query": tag,
                            "source_count": len(publishers), "basis": "publisher_tags", **momentum(mentions)})

    results.sort(key=lambda row: (row["momentum"] != "rising", -row["source_count"], -row["count"], row["query"]))
    return {
        "trending": results[:limit],
        "total_analyzed": len(pool),
        "window_hours": hours,
        "momentum_window_hours": hours / 2,
        "updated_at": now.isoformat(),
    }
