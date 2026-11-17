"""Coverage visibility and URL checks against the archive; never fetch user URLs."""
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.coverage import TOPICS, public_article
from app.ingestion import feed_freshness, source_catalog
from app.launch_store import get_store
from app.news import canonical_url
from app.sources import BY_ID

router = APIRouter(prefix="/api/discovery")


@router.get("/coverage")
def coverage(response: Response):
    store = get_store()
    if not store:
        raise HTTPException(503, "The persistent archive is unavailable.")
    catalog = source_catalog(store)
    diagnostics = store.feed_diagnostics()
    counts = store.coverage_counts()
    response.headers["Cache-Control"] = "public, max-age=30"
    topics = []
    for key, label in TOPICS.items():
        feeds = [feed for feed in catalog if BY_ID[feed["id"]].topic == key and feed["enabled"]]
        topics.append({"id": key, "label": label, "feeds": len(feeds),
            "publisher_groups": len({feed["source"] for feed in feeds}),
            "fresh_feeds": sum(feed["freshness"] == "fresh" for feed in feeds),
            "articles_24h": counts.get(key, 0)})
    return {"freshness": feed_freshness(catalog), "topics": topics,
        "feeds": [{"id": feed["id"], "label": feed["label"], "freshness": feed["freshness"],
            "integration": feed["integration"], "retained_count": feed["retained_count"],
            "observed_entries": diagnostics.get(feed["id"], {}).get("observed"),
            "rejected_entries": diagnostics.get(feed["id"], {}).get("rejected"),
            "diagnostics_at": diagnostics.get(feed["id"], {}).get("updated"),
            "last_success": feed["last_success"], "error": feed.get("error"), "retry_at": feed.get("retry_at")}
            for feed in catalog],
        "notice": "Feed checks measure synchronization, not exhaustive coverage. Topic feed counts use configured focus; article counts use story classification."}


@router.get("/check")
def check_article(url: Annotated[str, Query(min_length=10, max_length=2048)], request: Request, response: Response):
    from app.server import rate_limit
    rate_limit(request, "discovery-check", 30)
    try:
        canonical = canonical_url(url)
    except ValueError:
        raise HTTPException(422, "Paste an original publisher HTTPS article link.") from None
    store = get_store()
    if not store:
        raise HTTPException(503, "The persistent archive is unavailable.")
    host = urlsplit(canonical).hostname.removeprefix("www.")
    known = {entry.id for entry in BY_ID.values() if host in {domain.removeprefix("www.") for domain in entry.hosts}}
    articles = store.lookup_url(canonical)
    feeds = [feed for feed in source_catalog(store) if feed["id"] in known]
    status = ("indexed" if articles else "unsupported_source" if not feeds else
              "awaiting_sync" if any(feed["freshness"] == "pending" for feed in feeds) else
              "source_unavailable" if all(feed["freshness"] in {"failed", "paused"} for feed in feeds) else "not_in_archive")
    response.headers["Cache-Control"] = "no-store"
    return {"status": status, "url": canonical, "articles": [public_article(article) for article in articles],
            "sources": [{key: feed.get(key) for key in ("id", "label", "freshness", "error", "retry_at", "last_success")}
                        for feed in feeds],
            "notice": "Checks the retained 90-day archive and original links in community submissions. No page is fetched. A healthy feed can omit an article after it rotates out."}
