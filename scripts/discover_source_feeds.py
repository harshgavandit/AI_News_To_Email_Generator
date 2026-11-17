"""Inspect publisher-declared RSS/Atom links without activating sources.

Usage: python -m scripts.discover_source_feeds https://publisher.example/blog
Review the publisher, article hosts, dates and permissions before adding a pack.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
from pathlib import Path
import threading
from urllib.parse import urljoin
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.article_metadata import public_link
from app.news import fetch_bytes


def discover(url, fetch=fetch_bytes):
    if not public_link(url):
        raise ValueError("Use a public HTTPS publisher page")
    soup = BeautifulSoup(fetch(url), "html.parser")
    feeds = {}
    for link in soup.select('link[rel="alternate"][href]'):
        media_type = link.get("type", "").lower()
        if media_type not in {"application/rss+xml", "application/atom+xml"}:
            continue
        target = public_link(urljoin(url, link["href"]))
        if target:
            feeds[target] = {"url": target, "type": media_type, "discovered_from": url}
        if len(feeds) == 20:
            break
    return list(feeds.values())


def discover_many(seeds, fetch=fetch_bytes):
    """Check reviewed publisher pages, isolating failures and bounding host traffic."""
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 150:
        raise ValueError("Supply 1 to 150 reviewed publisher HTTPS pages")
    if any(not isinstance(url, str) or not public_link(url) for url in seeds):
        raise ValueError("Use public HTTPS publisher pages")
    gates = {urlsplit(url).hostname: threading.Semaphore(2) for url in seeds}

    def check(url):
        try:
            with gates[urlsplit(url).hostname]:
                feeds = discover(url, fetch)
            return {"page": url, "status": "discovered" if feeds else "no_declared_feed", "feeds": feeds}
        except Exception as error:
            return {"page": url, "status": "unavailable", "error": type(error).__name__, "feeds": []}

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, dict.fromkeys(seeds)))
    return {"checked_at": datetime.now(UTC).isoformat(), "activated": False, "results": results,
            "notice": "Discovery does not establish permission, feed validity or relevance. Review and validate before enabling."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--seeds", type=Path, help="JSON array of reviewed publisher pages")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if bool(args.url) == bool(args.seeds):
        parser.error("Choose one publisher URL or --seeds")
    report = (discover_many(json.loads(args.seeds.read_text(encoding="utf-8"))) if args.seeds else
              {"feeds": discover(args.url), "activated": False})
    encoded = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
