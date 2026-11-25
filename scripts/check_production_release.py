"""Verify a Vercel revision on the canonical public domain."""

from __future__ import annotations

import argparse
import json
import re
import time
from urllib.request import urlopen

SITE = "https://getinformdaily.com"


def fetch(path: str, content_type: str) -> tuple[bytes, str]:
    with urlopen(SITE + path, timeout=10) as response:
        if (
            response.status != 200
            or response.headers.get_content_type() != content_type
        ):
            raise ValueError(f"{path}: unexpected HTTP status or content type")
        return response.read(), response.headers.get("X-Informa-Revision", "")


def verify_payloads() -> None:
    for route, marker in (("/", b"Informa AI"), ("/research.html", b"Research Desk")):
        body, _ = fetch(route, "text/html")
        if marker not in body:
            raise ValueError(f"{route}: expected page text missing")
    body, _ = fetch("/api/news?hours=168&limit=1&catalog=0", "application/json")
    if not isinstance(json.loads(body).get("articles"), list):
        raise ValueError("/api/news: expected an archive article list")
    body, _ = fetch("/feeds/latest.xml", "application/rss+xml")
    if b"<rss" not in body:
        raise ValueError("/feeds/latest.xml: expected an RSS document")


def verify(revision: str, wait_seconds: int) -> None:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            body, actual_revision = fetch("/api/health", "application/json")
            if actual_revision != revision:
                raise ValueError(
                    f"Serving {actual_revision or 'a revision without an identifier'}"
                )
            if json.loads(body).get("status") != "ok":
                raise ValueError("/api/health: unhealthy response")
            verify_payloads()
            _, final_revision = fetch("/api/health", "application/json")
            if final_revision != revision:
                raise ValueError("The production alias changed during the smoke test")
        except (OSError, ValueError) as error:
            if time.monotonic() >= deadline:
                raise SystemExit(
                    f"::error::Production smoke failed for {revision}: {error}"
                ) from error
            print(f"Waiting for {revision[:12]}: {error}", flush=True)
            time.sleep(15)
        else:
            print(
                f"Verified production revision {revision} · health, home, research, archive, and RSS"
            )
            return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision")
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision) or args.wait_seconds < 0:
        parser.error("provide a full commit SHA and a nonnegative wait")
    verify(args.revision, args.wait_seconds)


if __name__ == "__main__":
    main()
