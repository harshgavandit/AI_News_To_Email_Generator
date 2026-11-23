"""Print discovered feeds as a Markdown table for the GitHub run page.

Usage: python -m scripts.summarize_discovery reports/discovered-feeds.json
Feeds already in the catalog are marked so reviewers only look at new ones.
"""
import argparse
import glob
import json
from pathlib import Path

from app.sources import DEFAULT_SOURCES


def known_urls():
    return {source.url.rstrip("/").lower() for source in DEFAULT_SOURCES}


def tried_urls(root=Path(__file__).resolve().parents[1]):
    """Feed addresses already checked in a candidate pack, promoted or not."""
    urls = set()
    for pack in glob.glob(str(root / "docs" / "research" / "source-candidates-*.json")):
        urls |= {row["url"].rstrip("/").lower() for row in json.loads(Path(pack).read_text(encoding="utf-8"))}
    return urls


def summarize(report, known, tried=frozenset()):
    rows, new = [], []
    for result in report.get("results", []):
        feeds = result.get("feeds") or []
        if not feeds:
            rows.append(f"| {result.get('page', '')} | {result.get('status', '')} | {result.get('error', '')} |")
            continue
        for feed in feeds:
            url = feed.get("url", "")
            key = url.rstrip("/").lower()
            status = "already in catalog" if key in known else "checked before" if key in tried else "new"
            if status == "new":
                new.append(url)
            rows.append(f"| {result.get('page', '')} | {status} | {url} |")
    head = [f"New feeds to review: {len(new)}", "", "| Page | Status | Feed or error |", "| --- | --- | --- |"]
    return "\n".join(head + rows + ["", "NEW_FEEDS=" + " ".join(new)]) + "\n", new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    text, _ = summarize(json.loads(args.report.read_text(encoding="utf-8")), known_urls(), tried_urls())
    print(text)


if __name__ == "__main__":
    main()
