"""Stable technology identifiers and evidence from the retained archive."""
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from urllib.parse import urlsplit

from sqlalchemy import or_

from app import research
from app.coverage import public_article
from app.discovery import search_text
from app.intelligence import deduplicate, references
from app.launch_store import articles, search_document


@dataclass(frozen=True)
class Technology:
    name: str
    aliases: tuple[str, ...]
    sources: tuple[str, ...]
    homepage: str
    identifiers: tuple[str, ...] = ()


TECHNOLOGIES = {
    "kubernetes": Technology("Kubernetes", ("Kubernetes", "k8s"),
        ("kubernetes", "kubernetes-blog", "kubernetes-zh", "kubernetes-advisories", "kubernetes-releases"),
        "https://kubernetes.io/", ("github.com/kubernetes/kubernetes",)),
    "postgresql": Technology("PostgreSQL", ("PostgreSQL", "Postgres"), ("postgresql",), "https://www.postgresql.org/"),
    "nodejs": Technology("Node.js", ("Node.js", "NodeJS", "Node JS"), ("node-releases",),
        "https://nodejs.org/", ("github.com/nodejs/node",)),
    "rust": Technology("Rust", ("Rust programming", "Rust compiler", "Rust language", "rustlang"),
        ("rust-releases",), "https://www.rust-lang.org/", ("github.com/rust-lang/rust",)),
    "google-cloud": Technology("Google Cloud", ("Google Cloud", "Google Kubernetes Engine", "GCP"),
        ("google-cloud-status",), "https://cloud.google.com/"),
    "openai": Technology("OpenAI", ("OpenAI", "ChatGPT"), ("openai-news",), "https://openai.com/"),
}

BREAKING = re.compile(r"\b(?:breaking changes?|(?:API|endpoint|parameter) (?:has been )?removed|removed (?:the |an? )?(?:[\w.-]+ ){0,5}(?:API|endpoint|parameter))\b", re.I)


def catalog():
    return [{"id": key, "name": tech.name, "homepage": tech.homepage} for key, tech in TECHNOLOGIES.items()]


def match(ident, row):
    tech = TECHNOLOGIES[ident]
    if row.get("source_id") in tech.sources:
        return "registered_source"
    for url in (row.get("url"), row.get("original_url")):
        if url:
            parsed = urlsplit(url)
            path = f"{parsed.hostname}{parsed.path}".lower().rstrip("/")
            if any(path == reference or path.startswith(reference + "/") for reference in tech.identifiers):
                return "repository"
    text = search_text(f"{row['title']} {row.get('description') or row.get('cleanSummary', '')}")
    if any(research.contains_term(text, search_text(alias)) for alias in tech.aliases):
        return "mention"
    return None


def record_kind(row):
    coverage = row["coverage"]
    if coverage in {"release", "advisory", "status"}:
        return coverage
    if coverage in {"preprint", "journal"}:
        return "research"
    return "reporting" if coverage == "reporting" else "community" if coverage in {"discussion", "article"} else "publisher"


def eligible_rows(store, ident, hours, *, now=None, limit=60):
    tech = TECHNOLOGIES[ident]
    source_match = articles.c.source_id.in_(tech.sources)
    terms = [search_document.contains(search_text(alias), autoescape=True) for alias in tech.aliases]
    links = [articles.c.url.contains(reference, autoescape=True) for reference in tech.identifiers]
    scope = store.query(hours, now=now)
    ordered = (articles.c.published_at.desc(), articles.c.id)
    with store.engine.connect() as conn:
        official = conn.execute(scope.where(source_match).order_by(*ordered).limit(100)).mappings().all()
        related = conn.execute(scope.where(~source_match, or_(*terms, *links)).order_by(*ordered).limit(200)).mappings().all()
    records = [record for row in deduplicate([*official, *related]) if (record := technology_record(ident, row))]
    records.sort(key=lambda row: (row["published_at"], row["id"]), reverse=True)
    # Preserve coverage of less frequent sources at the top of a busy technology's archive.
    groups = {}
    for row in records:
        groups.setdefault(row["record_kind"], []).append(row)
    selected = []
    for index in range(limit):
        for queue in groups.values():
            if index < len(queue):
                selected.append(queue[index])
        if len(selected) >= min(limit, len(records)):
            break
    return sorted(selected[:limit], key=lambda row: (row["published_at"], row["id"]), reverse=True)


def technology_record(ident, raw):
    basis = match(ident, raw)
    if not basis:
        return None
    row = public_article(raw)
    return {**research.evidence_record(row), "entity_match": basis, "record_kind": record_kind(row),
            "references": sorted(references(row)), "source_id": row["source_id"],
            "observed_category": row["topic"]}


def edition(store, ident, hours, question, language):
    rows = eligible_rows(store, ident, hours, limit=24)
    # Choose at least one item from represented source types before filling the context.
    types = set()
    diverse = []
    for row in rows:
        if row["excerpt"] and row["record_kind"] not in types:
            types.add(row["record_kind"])
            diverse.append(row)
    selected = {row["id"] for row in diverse}
    evidence = [*diverse, *(row for row in rows if row["id"] not in selected)][:12]
    subject = TECHNOLOGIES[ident].name
    task = f"Subject: {subject}. Past {hours} hours. Question: {question or 'What changed?'}"
    return {"evidence": evidence, "answer": research.synthesize(store, "technology", task, evidence,
        cacheable=not question, language=language), "generated_at": datetime.now(UTC).isoformat()}
