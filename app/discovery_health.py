"""Coverage visibility and URL checks against the archive; never fetch user URLs."""
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response
from xml.etree.ElementTree import Element, SubElement, tostring

from app.coverage import TOPICS, public_article
from app.ingestion import feed_freshness, source_catalog, ingestion_health
from app.news_signals import SIGNALS, story_signals
from app.launch_store import get_store
from app.news import canonical_url
from app.sources import BY_ID

router = APIRouter(prefix="/api/discovery")
FORMATS = {"news": "News", "blog": "Technical blogs", "newsletter": "Newsletters", "paper": "Research papers",
           "release": "Project releases", "video": "Video channels", "podcast": "Podcasts"}


@router.get("/sources/{source_id}/health")
def source_health(source_id: str, response: Response, hours: Annotated[int, Query(ge=1, le=168)] = 24):
    if source_id not in BY_ID:
        raise HTTPException(404, "Unknown reviewed source.")
    store = get_store()
    if not store:
        raise HTTPException(503, "The persistent archive is unavailable.")
    current = next(source for source in source_catalog(store) if source["id"] == source_id)
    response.headers["Cache-Control"] = "no-store"
    return {"source": current, "history": store.source_health_history(source_id, hours)}


@router.get("/sources.opml")
def export_sources():
    root = Element("opml", version="2.0")
    head = SubElement(root, "head")
    SubElement(head, "title").text = "Informa AI reviewed source feeds"
    body = SubElement(root, "body")
    catalog = source_catalog(get_store(), include_archive=False)
    for key, label in FORMATS.items():
        category = SubElement(body, "outline", text=label, title=label)
        for feed in catalog:
            if feed["enabled"] and feed["format"] == key and feed["integration"] == "rss":
                SubElement(category, "outline", type="rss", text=feed["label"], title=feed["label"], xmlUrl=feed["feed_url"])
    return Response(tostring(root, encoding="utf-8", xml_declaration=True), media_type="text/x-opml",
                    headers={"Content-Disposition": 'attachment; filename="informa-sources.opml"', "Cache-Control": "no-store"})


@router.get("/coverage")
def coverage(response: Response):
    store = get_store()
    if not store:
        raise HTTPException(503, "The persistent archive is unavailable.")
    catalog = source_catalog(store)
    diagnostics = store.feed_diagnostics()
    counts = store.coverage_counts()
    sample = store.headline_candidates(48, include_primary=True, per_source=12)
    signals = []
    for key, label, _, _ in SIGNALS:
        matches = [row for row in sample if key in {signal["id"] for signal in story_signals(row)}]
        signals.append({"id": key, "label": label, "sampled_articles": len(matches),
            "publisher_groups": len({BY_ID[row["source_id"]].publisher_family for row in matches}),
            "latest_published_at": max((row["published_at"] for row in matches), default=None),
            "gap": "no_matching_headlines_in_sample" if not matches else None})
    response.headers["Cache-Control"] = "public, max-age=30"
    topics = []
    for key, label in TOPICS.items():
        feeds = [feed for feed in catalog if BY_ID[feed["id"]].topic == key and feed["enabled"]]
        recent = counts.get(key, 0)
        fresh = sum(feed["freshness"] == "fresh" for feed in feeds)
        gap = ("no_sources" if not feeds else "checks_overdue" if not fresh else
               "no_recent_stories" if not recent else None)
        topics.append({"id": key, "label": label, "feeds": len(feeds),
            "publisher_groups": len({feed["publisher_family"] for feed in feeds}),
            "fresh_feeds": fresh, "articles_24h": recent, "gap": gap})
    return {"freshness": feed_freshness(catalog), "topics": topics, "signals": signals,
        "signal_sample_size": len(sample), "signal_window_hours": 48, "ingestion": ingestion_health(store, catalog),
        "attention": {"topics": [topic for topic in topics if topic["gap"]],
            "failed_sources": sum(feed["enabled"] and feed["freshness"] == "failed" for feed in catalog),
            "overdue_sources": sum(feed["enabled"] and feed["freshness"] == "stale" for feed in catalog),
            "quiet_sources": sum(feed["enabled"] and feed["content_status"] == "quiet" for feed in catalog)},
        "regions": [{"id": key, "sources": len(feeds),
            "fresh": sum(feed["freshness"] == "fresh" for feed in feeds),
            "publisher_groups": len({feed["publisher_family"] for feed in feeds})}
            for key in sorted({feed["region_id"] for feed in catalog})
            if (feeds := [feed for feed in catalog if feed["enabled"] and feed["region_id"] == key])],
        "formats": [{"id": key, "label": label, "sources": sum(feed["format"] == key for feed in catalog),
                     "fresh": sum(feed["format"] == key and feed["freshness"] == "fresh" for feed in catalog)}
                    for key, label in FORMATS.items()],
        "feeds": [{"id": feed["id"], "label": feed["label"], "freshness": feed["freshness"],
            "integration": feed["integration"], "retained_count": feed["retained_count"],
            "observed_entries": diagnostics.get(feed["id"], {}).get("observed"),
            "rejected_entries": diagnostics.get(feed["id"], {}).get("rejected"),
            "diagnostics_at": diagnostics.get(feed["id"], {}).get("updated"),
            "last_success": feed["last_success"], "error": feed.get("error"), "retry_at": feed.get("retry_at")}
            for feed in catalog],
        "notice": "Feed checks measure synchronization, not exhaustive coverage. Topic feed counts use configured focus; article counts use story classification."}


@router.get("/ingestion")
def ingestion_status(response: Response):
    store = get_store()
    if not store:
        raise HTTPException(503, "The persistent archive is unavailable.")
    response.headers["Cache-Control"] = "public, max-age=30"
    return ingestion_health(store)


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
