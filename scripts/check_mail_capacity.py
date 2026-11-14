"""Exercise 10,000 due subscriptions against a disposable database and a fake transport."""
import argparse
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from app import mail_batches, public_mail
from app.launch_store import Store, subscriptions


def exercise(url: str, count: int):
    store = Store(url)
    store.migrate()
    start = time.perf_counter()
    now = time.time()
    with store.engine.begin() as conn:
        for offset in range(0, count, 1000):
            rows = []
            for i in range(offset, min(offset + 1000, count)):
                email = f"capacity-reader-{i}@example.invalid"
                rows.append({"mailbox": public_mail.digest_key("mailbox:" + email), "email": email,
                             "timezone": "Asia/Kolkata", "next_run": now - 30, "enabled": True, "claimed": 0})
            conn.execute(subscriptions.insert(), rows)

    delivered, request_ids = set(), set()

    def fake_provider(url, *, json, headers, **options):
        assert url == "https://api.resend.com/emails/batch" and 0 < len(json) <= 100
        ident = headers["Idempotency-Key"]
        assert ident not in request_ids
        request_ids.add(ident)
        for message in json:
            recipient, = message["to"]
            assert recipient.endswith("@example.invalid") and recipient not in delivered
            assert message["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
            delivered.add(recipient)
        return httpx.Response(200, json={"data": [{"id": f"{ident}-{i}"} for i in range(len(json))]})

    ticks = 0
    with patch.object(mail_batches.httpx, "post", side_effect=fake_provider):
        while len(delivered) < count:
            result = mail_batches.run_batch_worker(store, lambda: {
                "html": "<html><body>Capacity fixture.</body></html>", "markdown": "Capacity fixture."})
            assert result["sent"] > 0 and result["unconfirmed"] == 0, result
            assert result["queued"] == 0
            ticks += 1
    assert store.mail_backlog(time.time())["due"] == 0
    elapsed = time.perf_counter() - start
    print(f"{store.engine.dialect.name}: {len(delivered):,} unique recipients, {len(request_ids)} provider calls, "
          f"{ticks} worker invocations, zero duplicates, {elapsed:.2f}s with synthetic transport.")
    store.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true", help="Use the isolated PostgreSQL service in CI.")
    args = parser.parse_args()
    with patch.dict(os.environ, {"RESEND_API_KEY": "fixture", "MAIL_FROM": "fixture@example.invalid",
                                  "MAIL_SESSION_SECRET": "disposable-capacity-test-secret-long",
                                  "MAIL_OUTBOUND_DAILY_LIMIT": "12000", "MAIL_DIGEST_DAILY_LIMIT": "12000"}):
        if args.postgres:
            # Intentionally accept only the disposable CI service, never an environment DB URL.
            exercise("postgresql://capacity:capacity@127.0.0.1:55432/capacity", 10_000)
        else:
            with TemporaryDirectory() as folder:
                exercise(f"sqlite:///{Path(folder, 'capacity.sqlite').as_posix()}", 10_000)


if __name__ == "__main__":
    main()
