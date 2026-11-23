"""Run a publisher sweep here (GitHub Actions) against the production database.

Usage:
  python -m scripts.run_publisher_sweep --run full
  python -m scripts.run_publisher_sweep --run priority

Feeds are fetched and parsed on this machine and written to NEWS_DATABASE_URL, so
Vercel only serves pages and its Active CPU allowance no longer limits how many sources
the catalog can hold. The sweep rules are the ones the site uses: one check per source
per sweep, the same windows, leases, backoffs and pruning.

After a full sweep has checked every feed, morning mail is started on the site
(PUBLIC_ORIGIN with FEED_REFRESH_SECRET) so briefs carry that sweep's news.
"""
import argparse
import logging
import os
import sys
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("publisher_sweep")

LEASE_WAIT_SECONDS = 30


def annotate(result):
    for failure in result.get("failures", ()):
        print(f"::warning::{failure['label']} ({failure['id']}): {failure['reason']}")
    for deferral in result.get("deferrals", ()):
        print(f"::warning::{deferral['label']} ({deferral['id']}): backoff until {deferral['retry_at']}")
    for ident in result.get("unconfirmed", ()):
        print(f"::error::{ident}: started without a recorded result.")


def sweep(kind, budget_seconds, *, sleep=time.sleep, clock=time.monotonic):
    """Run batches until the sweep is finished, closed or out of time; returns a summary."""
    from app import server

    deadline = clock() + budget_seconds
    checked = healthy = batches = 0
    result = {"status": "not_started", "remaining": None}
    while True:
        try:
            result = server.run_sweep(priority=True) if kind == "priority" else server.run_sweep(continuation=True)
        except HTTPException as error:
            logger.error("Sweep batch failed: %s", error.detail)
            return {"status": "stalled", "detail": error.detail, "checked": checked, "healthy": healthy,
                    "batches": batches}
        if result["status"] == "already_started":
            # Another run (Vercel or an overlapping GitHub run) holds the lease; wait for it.
            if clock() >= deadline:
                break
            sleep(LEASE_WAIT_SECONDS)
            continue
        batches += 1
        checked += result.get("checked", 0)
        healthy += result.get("healthy", 0)
        logger.info("batch=%s status=%s checked=%s healthy=%s remaining=%s deferred=%s", batches, result["status"],
                    result.get("checked"), result.get("healthy"), result.get("remaining"), result.get("deferred"))
        annotate(result)
        if result["status"] in ("closed", "complete") or not result.get("remaining") or clock() >= deadline:
            break
    return {**result, "checked": checked, "healthy": healthy, "batches": batches}


def start_morning_mail(origin, secret):
    url = urlsplit(origin)
    if url.scheme != "https" or not url.hostname or len(secret) < 16:
        logger.warning("PUBLIC_ORIGIN or FEED_REFRESH_SECRET is missing; morning mail waits for the site's own schedule.")
        return False
    try:
        reply = httpx.get(f"https://{url.hostname}/api/jobs/morning", headers={"Authorization": f"Bearer {secret}"},
                          timeout=110, follow_redirects=False)
        reply.raise_for_status()
    except httpx.HTTPError as error:
        print(f"::warning::Morning mail could not be started ({type(error).__name__}); the site's schedule will send it.")
        return False
    logger.info("Morning mail: %s", {key: value for key, value in reply.json().items() if key in ("status", "sent", "due")})
    return True


def outcome(kind, summary):
    """Exit code for the workflow: 0 when the sweep finished or its window had closed."""
    status = summary["status"]
    if status == "closed":
        print("::warning::This sweep window has closed; the next sweep covers the remaining sources.")
        return 0
    if status == "stalled":
        print(f"::error::Publisher sweep made no progress: {summary.get('detail')}")
        return 1
    if summary.get("remaining"):
        if kind == "priority":
            print("::warning::Priority check reached its time limit; the next full sweep covers the rest.")
            return 0
        print("::error::Publisher sweep reached its time limit before all eligible sources were checked.")
        return 1
    if summary.get("unconfirmed"):
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", choices=("full", "priority"), default="full")
    parser.add_argument("--budget-minutes", type=int, default=30)
    args = parser.parse_args(argv)
    if not os.getenv("NEWS_DATABASE_URL"):
        print("::error::Add the production NEWS_DATABASE_URL as a repository secret. See docs/LAUNCH.md.")
        return 1
    summary = sweep(args.run, args.budget_minutes * 60)
    logger.info("Sweep finished: status=%s checked=%s healthy=%s remaining=%s batches=%s", summary["status"],
                summary.get("checked"), summary.get("healthy"), summary.get("remaining"), summary.get("batches"))
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(f"### Publisher sweep ({args.run})\n\n| Status | Checked | Healthy | Remaining | Batches |\n"
                         "| --- | --- | --- | --- | --- |\n"
                         f"| {summary['status']} | {summary.get('checked', 0)} | {summary.get('healthy', 0)} | "
                         f"{summary.get('remaining') or 0} | {summary.get('batches', 0)} |\n")
    code = outcome(args.run, summary)
    if args.run == "full" and code == 0 and summary["status"] == "refreshed" and summary.get("checked"):
        start_morning_mail(os.getenv("PUBLIC_ORIGIN", "https://getinformdaily.com"), os.getenv("FEED_REFRESH_SECRET", ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
