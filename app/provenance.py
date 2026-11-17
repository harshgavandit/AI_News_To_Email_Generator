"""Observed source revisions and attributed relationships for retained evidence."""
import re

from sqlalchemy import select

from app import event_intelligence, research
from app.coverage import public_article
from app.discovery import search_text
from app.intelligence import references, story_identity

EDITORIAL_NOTICE = re.compile(r"^(?:(?:publisher|editor'?s?)\s+)?(correction|corrected|retraction|retracted)\s*[:\-–—]", re.I)


def notice(title):
    match = EDITORIAL_NOTICE.search(title)
    if not match:
        return None
    return "retraction" if match[1].lower().startswith("retract") else "correction"


def source_history(store, article_id):
    raw = store.pinned_articles([article_id])
    if not raw:
        return None
    article = public_article(raw[0])
    source = research.evidence_record(article)
    original = story_identity(article)
    result = {"source": source, "editorial_notice": notice(source["title"]), "event_id": None,
              "references": sorted(references(article)), "coverage": [], "revisions": []}
    if not event_intelligence.ready(store):
        return result
    with store.engine.connect() as conn:
        relation = event_intelligence.event_items
        event_id = conn.scalar(select(relation.c.event_id).where(relation.c.article_id == article_id))
    if not event_id or not (timeline := event_intelligence.timeline(store, event_id)):
        return result
    result["event_id"] = event_id
    excerpts = search_text(source["excerpt"])
    seen = set()
    for item in sorted(timeline["entries"], key=lambda entry: (entry["observed"], entry["id"])):
        current = research.evidence_record(item["source"])
        if current["id"] == article_id or item["reason"] == "source_revision":
            result["revisions"].append({"source_id": current["id"], "publisher": current["publisher"],
                "url": current["url"], "title": item["title"], "excerpt": item["excerpt"],
                "observed_at": item["observed"], "reason": item["reason"], "editorial_notice": notice(item["title"])})
        if current["id"] in seen:
            continue
        seen.add(current["id"])
        same_original = story_identity(item["source"]) == original and current["id"] != article_id
        repeated_excerpt = len(excerpts) >= 80 and search_text(current["excerpt"]) == excerpts and current["id"] != article_id
        relation = "same_original" if same_original else "matching_excerpt" if repeated_excerpt else "related_coverage"
        result["coverage"].append({**current, "relationship": relation, "editorial_notice": notice(current["title"])})
    result["coverage"].sort(key=lambda row: (row["published_at"], row["id"]))
    return result
