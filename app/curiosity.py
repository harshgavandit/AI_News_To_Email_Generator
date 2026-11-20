"""Source-grounded engineering stories for the Curiosity Cards collection."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import re

from app.article_language import is_english_article
from app.article_metadata import restore_metadata
from app.coverage import public_article
from app.discovery import search_text
from app.news import canonical_url
from app.sanitation import sanitize_text
from app.sources import BY_ID, DEFAULT_SOURCES


def _seed(ident, title, url, publisher, company, year, description, tags, read_minutes, source_id, *,
          authors="", publisher_detail="", read_time_basis="estimate"):
    return {
        "id": ident,
        "title": title,
        "url": url,
        "publisher": publisher,
        "company": company,
        "published_at": "",
        "year": int(year),
        "description": description,
        "summary": description,
        "summary_basis": "editorial_source_summary",
        "tags": list(tags),
        "read_minutes": read_minutes,
        "read_time_basis": read_time_basis,
        "estimated_reading_minutes": read_minutes,
        "reading_time_basis": read_time_basis,
        "source_id": source_id,
        "source": BY_ID[source_id].group,
        "kind": BY_ID[source_id].kind,
        "category": "Research" if BY_ID[source_id].kind == "research" else "Engineering",
        "author": authors,
        "publisher_detail": publisher_detail,
        "curiosity_seed": True,
    }


CURATED_CURIOSITY = (
    _seed("google-monorepo-2016", "Why Google Stores Billions of Lines of Code in a Single Repository",
          "https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/",
          "Google Research", "Google", 2016,
          "Google Research describes a common source of truth for tens of thousands of developers and the systems, workflows, benefits, and trade-offs behind working in one very large repository.",
          ("Monorepo", "Developer infrastructure", "Build systems"), 12, "google-research",
          authors="Rachel Potvin · Josh Levenberg", publisher_detail="Communications of the ACM, 59 (2016), pp. 78–87"),
    _seed("anthropic-opus-4-6", "Introducing Claude Opus 4.6",
          "https://www.anthropic.com/news/claude-opus-4-6", "Anthropic", "Anthropic", 2026,
          "Anthropic reports improvements in coding, longer-running agent work, and reliability across larger codebases, alongside a beta one-million-token context window.",
          ("Claude", "Coding", "AI systems", "Long context"), 10, "anthropic-news",
          publisher_detail="Anthropic model and systems update"),
    _seed("anthropic-long-context", "Prompt engineering for Claude’s long context window",
          "https://www.anthropic.com/news/prompting-long-context", "Anthropic", "Anthropic", 2023,
          "Anthropic’s case study tests quote extraction and examples drawn from other parts of a document as techniques for improving long-context recall.",
          ("Long context", "Evaluation", "Prompt engineering"), 12, "anthropic-news",
          publisher_detail="Anthropic technical case study"),
    _seed("openai-gpt-4-1-prompting", "GPT-4.1 Prompting Guide",
          "https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide", "OpenAI Cookbook", "OpenAI", 2025,
          "OpenAI’s archived guide shares prompting practices drawn from internal testing, including explicit instructions, examples, planning, and iterative evaluations. It may refer to outdated models or APIs.",
          ("Prompt engineering", "Agents", "Evaluation", "Archived guide"), 15, "openai-news",
          authors="Noah MacCallum · Julian Lee", publisher_detail="OpenAI Cookbook · archived reference"),
    _seed("flash-attention-eli5", "ELI5: FlashAttention",
          "https://gordicaleksa.medium.com/eli5-flash-attention-5c44017022ad", "Aleksa Gordić on Medium", "Independent research",
          2023,
          "A step-by-step explanation of FlashAttention’s tiling and recomputation strategy, and how reducing GPU memory traffic can make exact attention more efficient.",
          ("FlashAttention", "GPU systems", "Machine learning"), 20, "medium-gordicaleksa",
          authors="Aleksa Gordić", publisher_detail="Medium publisher estimate", read_time_basis="publisher"),
    _seed("attention-is-all-you-need", "Attention Is All You Need",
          "https://research.google/pubs/attention-is-all-you-need/", "Google Research", "Google", 2017,
          "The Transformer paper presents an attention-based sequence model that removes recurrence and uses attention to represent relationships between tokens.",
          ("Transformers", "Attention", "Machine learning"), 15, "google-research",
          authors="Ashish Vaswani and co-authors", publisher_detail="NeurIPS research paper"),
    _seed("google-file-system", "The Google File System",
          "https://research.google/pubs/the-google-file-system/", "Google Research", "Google", 2003,
          "Google’s paper explains a fault-tolerant distributed file system designed for large data-intensive workloads on commodity machines.",
          ("Distributed systems", "Storage", "Fault tolerance"), 14, "google-research",
          authors="Sanjay Ghemawat · Howard Gobioff · Shun-Tak Leung", publisher_detail="ACM SOSP research paper"),
    _seed("google-mapreduce", "MapReduce: Simplified Data Processing on Large Clusters",
          "https://research.google/pubs/mapreduce-simplified-data-processing-on-large-clusters/", "Google Research", "Google", 2004,
          "The MapReduce paper describes a programming model and runtime that parallelize data processing while handling partitioning, scheduling, machine failures, and communication across a cluster.",
          ("Distributed systems", "Data processing", "Cluster computing"), 12, "google-research",
          authors="Jeffrey Dean · Sanjay Ghemawat", publisher_detail="OSDI research paper"),
    _seed("google-bigtable", "Bigtable: A Distributed Storage System for Structured Data",
          "https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/", "Google Research", "Google", 2006,
          "The paper describes Bigtable’s data model and implementation for storing structured data at petabyte scale across thousands of commodity servers.",
          ("Distributed systems", "Databases", "Storage"), 12, "google-research",
          authors="Fay Chang and co-authors", publisher_detail="USENIX OSDI research paper"),
    _seed("google-spanner", "Spanner: Google’s Globally-Distributed Database",
          "https://research.google/pubs/spanner-googles-globally-distributed-database-2/", "Google Research", "Google", 2012,
          "Spanner’s paper explains a globally distributed, synchronously replicated database and the time API used to support externally consistent transactions.",
          ("Distributed systems", "Databases", "Consistency"), 14, "google-research",
          authors="James C. Corbett and co-authors", publisher_detail="OSDI research paper"),
    _seed("anthropic-source-control", "Redesigning source control at Anthropic",
          "https://www.anthropic.com/research/redesigning-source-control", "Anthropic Engineering", "Anthropic", 2026,
          "Anthropic describes redesigning developer infrastructure as Claude increased the pace of code changes, including the source-control, build, and CI bottlenecks that became more visible at higher throughput.",
          ("Developer infrastructure", "Source control", "Claude Code", "CI"), 12, "anthropic-engineering",
          publisher_detail="Anthropic engineering article"),
    _seed("openai-performance-factory", "How OpenAI’s Performance Factory keeps ChatGPT fast",
          "https://openai.com/index/how-openai-performance-factory-keeps-chatgpt-fast/", "OpenAI Engineering", "OpenAI", 2026,
          "OpenAI explains a cloud workflow that uses agents to investigate performance regressions, collect evidence, and propose fixes for an engineer to review.",
          ("Performance engineering", "AI agents", "ChatGPT infrastructure", "Regression testing"), 10, "openai-news",
          publisher_detail="OpenAI engineering article"),
    _seed("meta-template-driven-ml", "Design Once, Deploy at Scale: Building a Template-Driven ML Ecosystem",
          "https://engineering.fb.com/2026/11/18/ml-applications/design-once-deploy-at-scale-template-driven-ml-ecosystem/",
          "Engineering at Meta", "Meta", 2026,
          "Meta describes standardizing production model design around reusable components so teams can ship and maintain a large model portfolio with less per-model engineering work.",
          ("Machine learning systems", "Reusable architecture", "Production engineering"), 12, "meta-engineering",
          authors="Anirudh Agrawal and co-authors", publisher_detail="Engineering at Meta · ML Applications"),
    _seed("openai-postgres-chatgpt", "Scaling PostgreSQL to power 800 million ChatGPT users",
          "https://openai.com/index/scaling-postgresql/", "OpenAI Engineering", "OpenAI", 2026,
          "OpenAI’s systems case study describes how a single-primary PostgreSQL deployment and regional read replicas supported read-heavy product traffic, and why some write-heavy workloads moved to sharded systems.",
          ("PostgreSQL", "Distributed systems", "ChatGPT infrastructure", "Database scaling"), 14, "openai-news",
          publisher_detail="OpenAI engineering case study"),
    _seed("uber-artifact-storage", "Modernizing Artifact Storage at Uber",
          "https://www.uber.com/us/en/blog/modernizing-artifact-storage/", "Uber Engineering", "Uber", 2026,
          "Uber explains how it modernized storage and distribution for software build artifacts and dependencies used by downstream engineering teams.",
          ("Build systems", "Artifact storage", "Developer infrastructure"), 10, "uber-engineering",
          publisher_detail="Uber Engineering · English edition"),
    _seed("netflix-live-operations", "The Human Infrastructure: How Netflix Built the Operations Layer Behind Live at Scale",
          "https://netflixtechblog.com/the-human-infrastructure-how-netflix-built-the-operations-layer-behind-live-at-scale-33e2a311c597",
          "Netflix Technology Blog", "Netflix", 2026,
          "Netflix describes the live operations practices and teams developed to support a growing slate of live streams, including events reaching tens of millions of concurrent members.",
          ("Live streaming", "Reliability", "Operations", "Scaling"), 15, "netflix-techblog",
          authors="Brett Axler · Casper Choffat · Alo Lowry", publisher_detail="Netflix TechBlog · Medium publisher estimate",
          read_time_basis="publisher"),
)
SEEDS_BY_ID = {article["id"]: article for article in CURATED_CURIOSITY}

_technical_signals = {
    "architecture": re.compile(r"\barchitect(?:ure|ural)\b", re.I),
    "infrastructure": re.compile(r"\binfrastructure\b", re.I),
    "distributed systems": re.compile(r"\bdistributed\b|\breplication\b", re.I),
    "scaling": re.compile(r"\bscal(?:e|ed|ing|ability)\b|\bthroughput\b|\bcapacity\b", re.I),
    "reliability": re.compile(r"\breliab\w*\b|\bfault[- ]tolerant\b|\bavailability\b|\bpostmortem\b", re.I),
    "software design": re.compile(r"\bdesign(?:ed|ing)?\b|\bbuild system\b|\bmonorepo\b|\bcodebase\b", re.I),
    "data systems": re.compile(r"\bdatabase\w*\b|\bstorage\b|\bpipeline\b|\bdata movement\b", re.I),
    "performance": re.compile(r"\blatency\b|\bmemory\b|\bkernel\b|\bperformance\b|\bgpu\b", re.I),
    "engineering practice": re.compile(r"\bhow we (?:built|designed|scaled|migrated|operate|test)\b|\bincident report\b", re.I),
}
_promotional = re.compile(
    r"\b(?:sponsored|partner content|sign up|register now|webinar|giveaway|limited time|"
    r"introducing our new|now available|available today|pricing plans|product launch|buy now)\b", re.I)
_allowed_coverage = {"article", "publisher", "journal", "preprint"}
_company_names = {"google": "Google", "microsoft": "Microsoft", "amazon": "Amazon", "meta": "Meta",
                  "stripe": "Stripe", "uber": "Uber", "netflix": "Netflix", "airbnb": "Airbnb",
                  "spotify": "Spotify", "openai": "OpenAI", "anthropic": "Anthropic", "razorpay": "Razorpay"}
_technical_news_sources = {"openai-news", "anthropic-news"}


def curiosity_article(ident):
    """Return a copy of a manually reviewed source-backed card, if it is a seed."""
    article = SEEDS_BY_ID.get(ident)
    return deepcopy(article) if article else None


def curiosity_score(article):
    title = str(article.get("title", ""))
    description = str(article.get("description") or article.get("cleanSummary") or "")
    return sum((3 if matcher.search(title) else 0) + (1 if matcher.search(description) else 0)
               for matcher in _technical_signals.values())


def is_curiosity_candidate(article):
    """Keep cards to recent, English, excerpt-backed engineering insight."""
    source = BY_ID.get(article.get("source_id"))
    if not source or not source.enabled or (source.kind not in {"engineering", "research"}
                                               and source.id not in _technical_news_sources):
        return False
    if source.coverage not in _allowed_coverage or source.language not in {"en", "und"}:
        return False
    title = sanitize_text(article.get("title"), 500)
    description = sanitize_text(article.get("description") or article.get("cleanSummary"), 700)
    if len(title) < 16 or len(description) < 80 or _promotional.search(f"{title} {description}"):
        return False
    if not is_english_article({**article, "title": title, "description": description}):
        return False
    try:
        published = datetime.fromisoformat(str(article.get("published_at", "")).replace("Z", "+00:00"))
        if published.tzinfo is None:
            return False
        now = datetime.now(UTC)
        if published > now + timedelta(days=1) or published < now - timedelta(days=90):
            return False
    except (TypeError, ValueError):
        return False
    return curiosity_score({**article, "title": title, "description": description}) >= 3


def _candidate_sources():
    return tuple(source.id for source in DEFAULT_SOURCES if source.enabled
                 and (source.kind in {"engineering", "research"} or source.id in _technical_news_sources)
                 and source.coverage in _allowed_coverage
                 and source.language in {"en", "und"})


def _identity(article):
    try:
        url = canonical_url(article.get("url", ""))
    except (TypeError, ValueError):
        url = ""
    title = search_text(article.get("title", ""))
    return url, title, {term for term in title.split() if len(term) > 2}


def _is_duplicate(article, selected):
    url, title, terms = _identity(article)
    for existing in selected:
        other_url, other_title, other_terms = _identity(existing)
        if (url and url == other_url) or (title and title == other_title):
            return True
        if len(terms) >= 5 and len(other_terms) >= 5:
            union = terms | other_terms
            if union and len(terms & other_terms) / len(union) >= 0.84:
                return True
    return False


def _tags(article):
    text = f"{article.get('title', '')} {article.get('description', '')}".casefold()
    tags = []
    for label, matcher in _technical_signals.items():
        if matcher.search(text):
            tags.append(label.title())
    return tags[:4] or ["Engineering"]


def _company(article):
    source = BY_ID.get(article.get("source_id"))
    if not source:
        return article.get("publisher") or "Technology"
    if name := _company_names.get(source.publisher_family):
        return name
    label = source.label
    for suffix in (" on Medium", " TechBlog", " Engineering Blog", " Engineering", " Blog"):
        label = label.removesuffix(suffix)
    return label or source.label


def _estimated_read_minutes(article):
    measured = article.get("reading_time_minutes")
    if type(measured) is int and 1 <= measured <= 120:
        return measured, "publisher"
    estimate = article.get("estimated_reading_minutes")
    if type(estimate) is int and 1 <= estimate <= 120:
        return estimate, article.get("reading_time_basis", "estimate")
    # The app does not fetch full article bodies. Use a clearly marked editorial estimate.
    return 8, "estimate"


def _card(article, summaries):
    source = BY_ID.get(article.get("source_id"))
    public = public_article(article)
    summary = summaries.get(article["id"], {})
    read_minutes, read_basis = _estimated_read_minutes(article)
    published = str(article.get("published_at") or "")
    year_match = re.match(r"\d{4}", published)
    authors = sanitize_text(article.get("author"), 200)
    return {
        "id": article["id"],
        "title": public["title"],
        "company": article.get("company") or _company(article),
        "publisher": public["publisher"],
        "publisher_detail": article.get("publisher_detail", ""),
        "author": authors,
        "published_at": published,
        "year": article.get("year") or (int(year_match.group()) if year_match else None),
        "summary": sanitize_text(summary.get("summary") or public["cleanSummary"], 900),
        "summary_basis": summary.get("summary_basis") or public["summary_basis"],
        "tags": list(article.get("tags") or _tags(article))[:5],
        "read_minutes": read_minutes,
        "read_time_basis": read_basis,
        "url": public["url"],
        "source_id": article["source_id"],
        "kind": source.kind if source else article.get("kind", "engineering"),
        "description": article.get("description", ""),
        "seed": bool(article.get("curiosity_seed")),
    }


def build_curiosity_cards(store, *, limit=24):
    """Blend verified evergreen seeds with high-signal records in the archive."""
    limit = max(1, min(int(limit), 24))
    selected = [deepcopy(article) for article in CURATED_CURIOSITY[:limit]]
    remaining = limit - len(selected)
    if remaining and store:
        candidates = store.curiosity_candidates(_candidate_sources(), hours=90 * 24, limit=200)
        eligible = [restore_metadata(article) for article in candidates if is_curiosity_candidate(article)]
        # Stable tie-breaks: higher technical signal, then newer publication, then ID.
        eligible.sort(key=lambda item: str(item.get("id", "")))
        eligible.sort(key=lambda item: str(item.get("published_at", "")), reverse=True)
        eligible.sort(key=curiosity_score, reverse=True)
        for article in eligible:
            if _is_duplicate(article, selected):
                continue
            selected.append(article)
            if len(selected) == limit:
                break

    summaries = {}
    summary_targets = [article for article in selected if not article.get("curiosity_seed")]
    if summary_targets:
        try:
            from app.web_digest import build_digest
            digest = build_digest(summary_targets, "Reader", "Engineering systems and lessons learned", store=store,
                                  pinned_ids=[article["id"] for article in summary_targets], persona="engineer",
                                  style="technical", all_pool=summary_targets)
            summaries = {article["digest_id"]: article for article in digest.get("articles", [])}
        except Exception as error:
            # Preserve the source excerpt if model routing or response validation fails.
            import logging
            logging.getLogger(__name__).warning("curiosity_summary_unavailable error_type=%s", type(error).__name__)
    return [_card(article, summaries) for article in selected]


def resolve_curiosity_cards(store, ids):
    """Resolve only reviewed seeds or currently eligible archive articles, without AI calls."""
    requested = list(dict.fromkeys(ids))
    selected = []
    missing = []
    for ident in requested:
        seed = curiosity_article(ident)
        if seed:
            selected.append(seed)
        else:
            missing.append(ident)
    if missing and store:
        rows = store.pinned_articles(missing)
        by_id = {article["id"]: article for article in rows}
        for ident in missing:
            article = by_id.get(ident)
            if article and is_curiosity_candidate(restore_metadata(article)):
                selected.append(_card(restore_metadata(article), {}))
    by_id = {card["id"]: card for card in selected}
    return [by_id[ident] for ident in requested if ident in by_id]


def seed_article_ids():
    return set(SEEDS_BY_ID)
