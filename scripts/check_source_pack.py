"""Validate a proposed reviewed source pack before enabling it.

Run against a local JSON candidate list. Reports transport, parsed items and
recent-entry eligibility; never edits the production catalog or submits URLs to
the application. Use --promote only after reviewing the report and publishers.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import threading
import time

from app.news import read_feed
from app.sources import DEFAULT_SOURCES, Source, load_source_pack, validate_source
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--promote", type=Path)
    parser.add_argument("--recheck-existing", action="store_true")
    args = parser.parse_args()
    candidates = json.loads(args.input.read_text(encoding="utf-8"))
    existing_ids = {source.id for source in DEFAULT_SOURCES}
    existing_urls = {source.url for source in DEFAULT_SOURCES}
    gates = {}
    for row in candidates:
        gates.setdefault(urlsplit(row["url"]).hostname, threading.Semaphore(2))

    def check(row):
        started = time.monotonic()
        result = {"id": row["id"], "url": row["url"]}
        if not args.recheck_existing and (row["id"] in existing_ids or row["url"] in existing_urls):
            return dict(result, status="already_integrated")
        try:
            source = Source(**{key: tuple(value) if key in {"hosts", "article_paths", "excluded_paths", "sitemap_paths"}
                              else value for key, value in row.items()})
            validate_source(source)
            with gates[urlsplit(row["url"]).hostname]:
                items, state = read_feed(source)
            cutoff = datetime.now(UTC) - timedelta(days=90)
            recent = [item for item in items if cutoff <= datetime.fromisoformat(item["published_at"]) <= datetime.now(UTC)]
            result.update(status="active" if recent and state["available"] else "dormant" if state["available"] else "unavailable",
                parsed_entries=len(items), recent_entries=len(recent), error=state.get("error"),
                latest_published_at=max((item["published_at"] for item in items), default=None),
                sample_urls=[item["url"] for item in recent[:2]],
                seconds=round(time.monotonic() - started, 3))
        except Exception as error:
            result.update(status="invalid_configuration", error=type(error).__name__)
        return result

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(check, candidates))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "results": results}, indent=2), encoding="utf-8")
    if args.promote:
        active = {row["id"] for row in results if row["status"] == "active"}
        approved = [{**row, "reviewed_at": datetime.now(UTC).date().isoformat()} for row in candidates if row["id"] in active]
        args.promote.parent.mkdir(parents=True, exist_ok=True)
        retained = json.loads(args.promote.read_text(encoding="utf-8")) if args.promote.exists() else []
        merged = {row["id"]: row for row in retained}
        merged.update({row["id"]: row for row in approved})
        temporary = args.promote.with_suffix(args.promote.suffix + ".pending")
        temporary.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        load_source_pack(temporary)
        temporary.replace(args.promote)
    print(json.dumps({status: sum(row["status"] == status for row in results) for status in
                      ("active", "dormant", "unavailable", "already_integrated", "invalid_configuration")}))


if __name__ == "__main__":
    main()
