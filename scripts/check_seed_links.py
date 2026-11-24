"""Check that every reviewed Curiosity Card still links to a live page.

Runs on its own weekly schedule, separate from the feed fetches. Each seed URL is requested once
(HEAD, then GET when a site refuses HEAD). Results:

- ok: the page answered, possibly after a redirect on the same site
- moved: the page now redirects to a different site; review the card's link
- blocked: the site refused an automated check (401, 403, 429); check it by hand if it persists
- broken: 404, 410 or a server error; the card needs a new link or removal
- unreachable: no connection at all; usually the network running the check, so retry before acting

Exits with status 1 when any link is broken, so the scheduled run is flagged.

    uv run python -m scripts.check_seed_links --report reports/seed-links.json
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import requests

from app.curiosity import CURATED_CURIOSITY

USER_AGENT = "Mozilla/5.0 (compatible; InformaAI-LinkCheck/1.0; +https://getinformdaily.com/trust.html)"
BLOCKED = {401, 403, 429, 999}
GONE = {404, 410}


def _site(url):
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify(url, status, final_url, error=None):
    if error is not None or status is None:
        return "unreachable"
    if status in BLOCKED:
        return "blocked"
    if status in GONE or status >= 500:
        return "broken"
    if status >= 400:
        return "broken"
    if final_url and _site(final_url) and _site(final_url) != _site(url):
        return "moved"
    return "ok"


def check(url, session, timeout=20):
    error = None
    for attempt in range(2):
        try:
            response = session.head(url, allow_redirects=True, timeout=timeout)
            if response.status_code in {403, 405, 501} or response.status_code >= 500:
                response = session.get(url, allow_redirects=True, timeout=timeout, stream=True)
                response.close()
            return {"url": url, "status": response.status_code, "final_url": response.url,
                    "result": classify(url, response.status_code, response.url)}
        except requests.RequestException as caught:
            error = type(caught).__name__
            time.sleep(2 * (attempt + 1))
    return {"url": url, "status": None, "final_url": "", "error": error, "result": classify(url, None, "", error)}


def check_seeds(seeds=CURATED_CURIOSITY, *, workers=8, session=None):
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda seed: {"id": seed["id"], **check(seed["url"], session)}, seeds))
    return sorted(results, key=lambda row: (row["result"] == "ok", row["id"]))


def summary(results):
    counts = {}
    for row in results:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    lines = [f"## Curiosity seed links: {len(results)} checked", "",
             " · ".join(f"{name}: {counts.get(name, 0)}" for name in ("ok", "moved", "blocked", "broken", "unreachable")), ""]
    if counts.get("unreachable", 0) > len(results) / 2:
        lines += ["Most links could not be reached at all, so the network running this check is the likely cause. "
                  "Run it again from another network before changing any card.", ""]
    for row in results:
        if row["result"] != "ok":
            detail = row.get("error") or row["status"]
            moved = f" → {row['final_url']}" if row["result"] == "moved" else ""
            lines.append(f"- **{row['result']}** `{row['id']}` ({detail}) {row['url']}{moved}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path, help="Write the full results as JSON.")
    args = parser.parse_args(argv)
    results = check_seeds()
    print(summary(results))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 1 if any(row["result"] == "broken" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
