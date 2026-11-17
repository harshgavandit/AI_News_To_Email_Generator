"""Run on an always-on host. Uses the existing scheduled-job credential."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def monitor(origin: str, secret: str, path: str, interval: int):
    with httpx.Client(base_url=origin, headers={"Authorization": f"Bearer {secret}"},
                      timeout=110, follow_redirects=False) as client:
        while True:
            started = time.monotonic()
            next_run = None
            try:
                response = client.get(path)
                response.raise_for_status()
                result = response.json()
                metrics = {key: result[key] for key in ("status", "healthy", "sent", "due", "oldest_due_seconds",
                                                      "checked", "remaining", "deferred", "scheduled_at",
                                                      "index_status", "indexed", "brief_status",
                                                      "queued", "oldest_queued_seconds", "unconfirmed")
                           if key in result}
                logger.info("%s %s", path, metrics)
                if path == "/api/jobs/refresh" and result.get("scheduled_at"):
                    next_run = datetime.fromisoformat(result["scheduled_at"])
                if metrics.get("unconfirmed", 0) or max(metrics.get("oldest_due_seconds", 0),
                                                       metrics.get("oldest_queued_seconds", 0)) > 900:
                    logger.warning("Mail worker needs attention: %s", metrics)
            except (httpx.HTTPError, ValueError):
                logger.warning("%s failed. Retry on the next interval.", path)
            except Exception:
                logger.error("%s returned an unexpected response.", path)
            delay = max(1, interval - (time.monotonic() - started))
            if next_run:
                delay = max(delay, (next_run - datetime.now(timezone.utc)).total_seconds())
            time.sleep(delay)


def main():
    load_dotenv()
    origin = os.getenv("PUBLIC_ORIGIN", "")
    secret = os.getenv("FEED_REFRESH_SECRET", "")
    url = urlsplit(origin)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment or len(secret) < 16:
        raise SystemExit("Set the deployed HTTPS PUBLIC_ORIGIN and FEED_REFRESH_SECRET in the worker environment.")
    intelligence_enabled = os.getenv("NEWS_AI_WORKER", "0") == "1"
    with ThreadPoolExecutor(max_workers=3 if intelligence_enabled else 2) as pool:
        feeds = pool.submit(monitor, origin, secret, "/api/jobs/refresh", 30)
        mail = pool.submit(monitor, origin, secret, "/api/jobs/morning", 60)
        if intelligence_enabled:
            pool.submit(monitor, origin, secret, "/api/jobs/intelligence", 300)
        feeds.result()
        mail.result()


if __name__ == "__main__":
    main()
