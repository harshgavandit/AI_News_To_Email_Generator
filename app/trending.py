"""Extract trending technology topics, companies, and keywords from recent reporting."""
from datetime import UTC, datetime, timedelta
import re


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
            if pub >= cutoff:
                pool.append(a)
        except (ValueError, KeyError):
            continue

    results = []
    for label, category, pattern in TRENDING_PATTERNS:
        matcher = re.compile(pattern, re.I)
        count = sum(1 for a in pool if matcher.search(a.get("title", "")) or
                    matcher.search(a.get("cleanSummary") or a.get("description") or ""))
        if count > 0:
            results.append({
                "tag": label,
                "category": category,
                "count": count,
                "query": label.split("&")[0].strip().lower(),
            })

    results.sort(key=lambda t: t["count"], reverse=True)
    return {
        "trending": results[:limit],
        "total_analyzed": len(pool),
        "updated_at": now.isoformat(),
    }
