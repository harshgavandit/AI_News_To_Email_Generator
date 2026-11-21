"""Turn a natural-language search into reviewed filters plus residual keywords.

"ransomware advisories from European publishers this week" becomes the keyword
"ransomware", the advisory source type, the Europe publisher region and a 7-day
window. Parsing is deterministic and uses only the reviewed catalog, so it runs on
every keystroke without a model call. The reader confirms the interpretation
before it is applied; nothing is filtered silently.
"""
import re

from app.discovery import search_text

WINDOWS = (
    (r"(?:last|past) 12 hours", 12),
    (r"today|(?:in the )?(?:last|past) (?:day|24 hours)|this morning|tonight", 24),
    (r"this week|(?:in the )?(?:last|past) (?:week|7 days|seven days)", 168),
    (r"this month|(?:in the )?(?:last|past) (?:month|30 days|thirty days)", 720),
    (r"this quarter|(?:in the )?(?:last|past) (?:quarter|3 months|three months|90 days)", 2160),
)
WINDOW_LABELS = {12: "Past 12 hours", 24: "Past 24 hours", 168: "Past 7 days", 720: "Past 30 days", 2160: "Past 90 days"}
COVERAGE = (
    (r"release notes?|changelogs?|new releases|releases", "release"),
    (r"security advisories|advisories|advisory|cves", "advisory"),
    (r"research papers|papers|preprints|arxiv", "preprint"),
    (r"journal articles|journals", "journal"),
    (r"official announcements|press releases|announcements", "publisher"),
    (r"community discussions?|discussions|threads", "discussion"),
    (r"tutorials|how tos|guides", "article"),
)
SUBJECTS = (
    (r"ai agents|agentic ai|agentic|agents", "agents"),
    (r"large language models|llms|llm|inference", "llms"),
    (r"generative ai|genai", "generative-ai"),
    (r"mlops", "machine-learning"),
    (r"quantum computing|quantum", "quantum"),
    (r"humanoid robots|robotics|robots", "robotics"),
    (r"funding rounds?|fundraising|venture capital|funding|raises|series [a-e]", "funding"),
    (r"mergers? and acquisitions|m a|acquisitions?|acquires|mergers?", "acquisitions"),
    (r"open source", "open-source"),
    (r"satellites|space technology|space tech|spaceflight", "space"),
    (r"climate tech|energy tech|clean energy", "climate"),
    (r"databases|data engineering", "data"),
)
TOPICS = (
    (r"artificial intelligence|machine learning|ai", "ai"),
    (r"cybersecurity|cyber security|security|infosec|privacy", "security"),
    (r"semiconductors?|chips?|hardware", "chips"),
    (r"startups?|venture", "startups"),
    (r"big tech|tech companies", "bigtech"),
    (r"software|cloud|devops|developer", "software"),
    (r"science|research", "research"),
    (r"tech policy|regulation|policy", "industry"),
    (r"outages?|downtime", "outages"),
)
REGIONS = {
    "EU": r"europe|european|eu|uk|british|britain|germany|german|france|french|spain|spanish|italy|italian|dutch|nordic",
    "APAC": r"asia pacific|asia|asian|apac|india|indian|china|chinese|japan|japanese|korea|korean|australia|australian|singapore",
    "NA": r"north america|north american|us|usa|american|united states|canada|canadian",
    "LatAm": r"latin america|latam|latin american|brazil|brazilian|mexico|mexican|argentina",
    "Africa": r"africa|african|nigeria|nigerian|kenya|kenyan|south africa",
    "MENA": r"middle east|mena|israel|israeli|uae|gulf|saudi|egypt",
}
OUTLETS = r"(?:publishers?|outlets?|press|media|sources|newsrooms?|outlets)"
SCOPE_WORDS = r"(?:news|stories|story|articles|updates|headlines|coverage|reports|reporting)"
FILLERS = re.compile(r"\b(?:show me|find|search for|what s new in|what is happening (?:in|with)|what s happening (?:in|with)|"
                     r"latest|newest|most recent|recent|about|regarding|on|in|for|the|any|all|from|of|news|stories|story|"
                     r"articles|updates|headlines|coverage|reports|reporting|please)\b")
LATEST = re.compile(r"\b(?:latest|newest|most recent|breaking)\b")


def _take(text, pattern):
    """Remove the first whole-phrase match; return (remaining text, matched or None)."""
    match = re.search(rf"\b(?:{pattern})\b", text)
    if not match:
        return text, None
    return f"{text[:match.start()]} {text[match.end():]}", match.group(0)


def understand(query, *, topics, regions, coverage_types, subjects, sources=()):
    """Return an interpretation for a typed query, or None when no filter is implied."""
    text = " " + search_text(query or "") + " "
    if len(text.strip()) < 3:
        return None
    filters, labels = {}, []
    sort = "latest" if LATEST.search(text) else None

    for pattern, hours in WINDOWS:
        text, found = _take(text, pattern)
        if found:
            filters["hours"] = hours
            labels.append(WINDOW_LABELS[hours])
            break

    for region, names in REGIONS.items():
        # Region filters describe where a publisher is based, so require publisher wording.
        text, found = _take(text, rf"from (?:{names})(?: {OUTLETS})?|(?:{names}) {OUTLETS}")
        if found and region in regions:
            filters["region"] = region
            labels.append(f"{regions[region]} publishers")
            break

    for source in sources:
        if not getattr(source, "enabled", True):
            continue
        name = search_text(source.label)
        if len(name) >= 3:
            text, found = _take(text, rf"(?:from|on|by) {re.escape(name)}")
            if found:
                filters["publisher"] = source.id
                labels.append(source.label)
                break

    for pattern, key in COVERAGE:
        text, found = _take(text, pattern)
        if found and key in coverage_types:
            filters["coverage"] = key
            labels.append(coverage_types[key])
            break

    for pattern, key in SUBJECTS:
        text, found = _take(text, pattern)
        if found and key in subjects:
            filters["subject"] = key
            labels.append(subjects[key])
            break

    # A topic filter hides everything else, so apply it only when the reader names the topic as the scope:
    # "security news", "AI updates", or a query that is only the topic.
    rest = " ".join(FILLERS.sub(" ", text).split())
    for pattern, key in TOPICS:
        scoped = re.search(rf"\b(?:{pattern}) {SCOPE_WORDS}\b", text)
        if (scoped or re.fullmatch(rf"(?:{pattern})", rest)) and key in topics:
            text = text[:scoped.start()] + " " + text[scoped.end():] if scoped else ""
            filters["topic"] = key
            labels.insert(0, topics[key])
            break

    terms = " ".join(FILLERS.sub(" ", text).split())
    if not filters:
        return None
    filters["sort"] = sort or ("relevance" if terms else "latest")
    summary = " · ".join([f"“{terms}”"] * bool(terms) + labels)
    return {"query": query.strip(), "terms": terms, "filters": filters, "labels": labels, "summary": summary,
            "basis": "Interpreted from your words using the reviewed filter catalog. Nothing is applied until you choose it."}
