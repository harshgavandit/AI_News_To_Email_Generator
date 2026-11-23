"""Print discovered feeds as a Markdown table for the GitHub run page.

Usage: python -m scripts.summarize_discovery reports/discovered-feeds.json
Feeds already in the catalog are marked so reviewers only look at new ones.
"""
import argparse
import json
from pathlib import Path

from app.sources import DEFAULT_SOURCES


def known_urls():
    return {source.url.rstrip("/").lower() for source in DEFAULT_SOURCES}


def summarize(report, known):
    rows, new = [], []
    for result in report.get("results", []):
        feeds = result.get("feeds") or []
        if not feeds:
            rows.append(f"| {result.get('page', '')} | {result.get('status', '')} | {result.get('error', '')} |")
            continue
        for feed in feeds:
            url = feed.get("url", "")
            fresh = url.rstrip("/").lower() not in known
            if fresh:
                new.append(url)
            rows.append(f"| {result.get('page', '')} | {'new' if fresh else 'already in catalog'} | {url} |")
    head = [f"New feeds to review: {len(new)}", "", "| Page | Status | Feed or error |", "| --- | --- | --- |"]
    return "\n".join(head + rows + ["", "NEW_FEEDS=" + " ".join(new)]) + "\n", new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    text, _ = summarize(json.loads(args.report.read_text(encoding="utf-8")), known_urls())
    print(text)


if __name__ == "__main__":
    main()
