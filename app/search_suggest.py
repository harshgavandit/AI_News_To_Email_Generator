"""Search scope suggestions for the Reading Room search box.

Suggestions come only from reviewed catalog data (topics, subjects, enabled
publisher feeds) and author names observed in the recent archive sample. No
model call or publisher request is made, so the endpoint is cheap and safe to
call while a reader types.
"""
from app.discovery import search_text

KINDS = ("topic", "subject", "publisher", "author")
PER_KIND = {"topic": 3, "subject": 3, "publisher": 5, "author": 4}


def match_score(query: str, label: str) -> int:
    """Rank a label against a folded query: exact > prefix > word prefix > substring."""
    text = search_text(label)
    if not query or not text:
        return 0
    if text == query:
        return 400
    if text.startswith(query):
        return 300 - min(len(text), 99)
    if any(word.startswith(query) for word in text.split()):
        return 200 - min(len(text), 99)
    if query in text:
        return 100 - min(len(text), 99)
    return 0


def suggest(query: str, *, topics: dict, subjects: dict, sources, authors=(), limit: int = 12) -> list[dict]:
    """Return grouped scope suggestions ordered by kind, then match quality."""
    phrase = search_text(query or "").strip()
    if len(phrase) < 2:
        return []
    candidates = {kind: [] for kind in KINDS}
    for key, label in topics.items():
        candidates["topic"].append((match_score(phrase, label) or match_score(phrase, key), {"id": key, "label": label}))
    for key, label in subjects.items():
        candidates["subject"].append((match_score(phrase, label), {"id": key, "label": label}))
    seen_publishers = set()
    for source in sources:
        if not getattr(source, "enabled", True) or source.id in seen_publishers:
            continue
        seen_publishers.add(source.id)
        candidates["publisher"].append((match_score(phrase, source.label), {"id": source.id, "label": source.label,
                                                                            "detail": source.region}))
    seen_authors = set()
    for author in authors:
        name = (author.get("name") or "").strip()
        key = author.get("id") or name
        if not name or key in seen_authors:
            continue
        seen_authors.add(key)
        candidates["author"].append((match_score(phrase, name), {"id": key, "label": name,
                                                                 "detail": author.get("publisher") or ""}))
    results = []
    for kind in KINDS:
        ranked = sorted((row for row in candidates[kind] if row[0] > 0), key=lambda row: (-row[0], row[1]["label"].casefold()))
        results.extend({"kind": kind, **item} for _, item in ranked[:PER_KIND[kind]])
    return results[:limit]
