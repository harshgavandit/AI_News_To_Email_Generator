"""Inspect publisher-declared RSS/Atom links without activating sources.

Usage: python -m scripts.discover_source_feeds https://publisher.example/blog
Review the publisher, article hosts, dates and permissions before adding a pack.
"""
import argparse
import json
from urllib.parse import urljoin

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    args = parser.parse_args()
    print(json.dumps({"feeds": discover(args.url), "activated": False}, indent=2))


if __name__ == "__main__":
    main()
