"""Check reviewed public integrations without writing the archive or calling AI/email."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
import time

from app.news import FEED_WORKERS, read_feed
from app.sources import BY_ID, DEFAULT_SOURCES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=tuple(BY_ID), help="Check selected reviewed source IDs")
    args = parser.parse_args()
    selected = [source for source in DEFAULT_SOURCES if source.enabled and (not args.source or source.id in args.source)]
    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=FEED_WORKERS) as pool:
        futures = {pool.submit(read_feed, source): source for source in selected}
        for future in as_completed(futures):
            source = futures[future]
            try:
                items, status = future.result()
                result = {"id": source.id, "available": status["available"], "count": len(items),
                          "latest_published_at": max((row["published_at"] for row in items), default=None),
                          "transport": status.get("transport", source.integration)}
                if status.get("error"):
                    result["error"] = status["error"]
            except Exception as error:
                result = {"id": source.id, "available": False, "count": 0, "error": type(error).__name__}
            results.append(result)
    healthy = sum(result["available"] for result in results)
    print(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "total": len(results), "healthy": healthy,
                      "articles": sum(result["count"] for result in results),
                      "seconds": round(time.monotonic() - started, 2), "sources": sorted(results, key=lambda row: row["id"])}, indent=2))
    return int(healthy != len(results))


if __name__ == "__main__":
    raise SystemExit(main())
