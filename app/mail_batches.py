"""Durable Resend batches for opted-in daily briefs."""
import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime

import httpx

from app import public_mail
from app.brand import DAILY_SUBJECT
from app.mail_capacity import batch_sender, mail_capacity

MAX_BATCH_SIZE = 100
MAX_BATCHES_PER_TICK = 10
WORKER_LEASE = "morning-mail-lease"
logger = logging.getLogger(__name__)


def dispatch_batch(store, row):
    messages = json.loads(row["message"])
    mailboxes = json.loads(row["recipients"])
    now = time.time()
    attempts = row["attempts"] + 1
    created = datetime.fromtimestamp(row["created"], UTC)
    if now - row["created"] >= 1800 or created.date().isoformat() != public_mail.day():
        store.update_mail_batch(row["id"], "expired", row["attempts"], now)
        return 0, row["size"]
    if row["attempts"] >= 5:
        store.update_mail_batch(row["id"], "unconfirmed", row["attempts"], now)
        return 0, row["size"]
    active = store.active_batch_mailboxes(mailboxes)
    if not all(mailbox in active for mailbox in mailboxes):
        if row["attempts"]:
            # An earlier attempt might have reached Resend. Its payload must stay identical.
            store.update_mail_batch(row["id"], "unconfirmed", row["attempts"], now)
            return 0, row["size"]
        kept = [(mailbox, message) for mailbox, message in zip(mailboxes, messages) if mailbox in active]
        mailboxes = [mailbox for mailbox, _ in kept]
        messages = [message for _, message in kept]
        if not messages:
            store.update_mail_batch(row["id"], "cancelled", row["attempts"], now)
            return 0, 0
        store.replace_unattempted_batch(row["id"], messages, mailboxes)
    store.update_mail_batch(row["id"], "pending", attempts, now + 30, size=len(messages))
    delay = 0
    try:
        response = httpx.post("https://api.resend.com/emails/batch", json=messages,
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Idempotency-Key": row["id"]},
            timeout=httpx.Timeout(6, connect=3), follow_redirects=False)
        status = response.status_code
        if response.is_success:
            data = response.json().get("data", [])
            if len(data) == len(messages) and all(isinstance(item, dict) and item.get("id") for item in data):
                store.record_mail_batch_events(row["id"], mailboxes)
                store.update_mail_batch(row["id"], "accepted", attempts, now)
                return len(messages), 0
        transient = status in (408, 409, 429) or status >= 500 or response.is_success
        retry_after = response.headers.get("retry-after", "")
        delay = min(900, int(retry_after)) if retry_after.isdecimal() else 0
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        transient = True
    if transient and attempts < 5:
        store.update_mail_batch(row["id"], "pending", attempts, now + max(delay, 30 * 2 ** (attempts - 1)))
        return 0, 0
    store.update_mail_batch(row["id"], "unconfirmed" if transient else "rejected", attempts, now)
    return 0, len(messages)


def run_batch_worker(store, generate_fn, *, maximum=MAX_BATCHES_PER_TICK):
    from app.mail_schedule import (morning_curiosity, next_morning, with_unsubscribe,
                                   build_unsubscribe_url, morning_event_loader, personalized_morning_brief)

    sender = batch_sender()
    lease = store.claim_refresh(scope=WORKER_LEASE)
    result = {"sent": 0, "unconfirmed": 0, "mode": "batch", "busy": lease is None}
    if lease is None:
        return result
    started = time.monotonic()
    brief = None
    load_events = morning_event_loader(store)
    try:
        for index in range(maximum):
            if time.monotonic() - started > 65:
                break
            now = time.time()
            row = store.pending_mail_batch()
            if row and row["retry_at"] > now:
                break
            if not row:
                if not store.has_due_subscription(now):
                    break
                if brief is None:
                    brief = generate_fn()
                moment = datetime.fromtimestamp(now, UTC)

                def message_for(subscription):
                    url = build_unsubscribe_url(subscription["mailbox"])
                    content = personalized_morning_brief(store, subscription["mailbox"], brief, load_events)
                    next_run = next_morning(subscription["timezone"], moment)
                    if content is None:
                        return None, next_run
                    history = content.get("_catchup")
                    content = with_unsubscribe(content, url, scheduled=True)
                    content = morning_curiosity(store, subscription["mailbox"], content, moment, subscription["timezone"])
                    message = {"from": sender, "to": [subscription["email"]], "subject": DAILY_SUBJECT,
                            "text": content["markdown"], "html": content["html"], "headers": {
                                "List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                            }}
                    if history:
                        message["_informa_event_history"] = history
                    return message, next_run

                batch_id = secrets.token_hex(24)
                if not store.enqueue_morning_batch(batch_id, now, moment.date().isoformat(), mail_capacity(),
                                                   MAX_BATCH_SIZE, message_for):
                    break
                row = store.pending_mail_batch()
            sent, failed = dispatch_batch(store, row)
            result["sent"] += sent
            result["unconfirmed"] += failed
            if not sent:
                break
            if index + 1 < maximum:
                time.sleep(0.25)  # Leave headroom for instant mail on the same provider account.
        return result | store.mail_backlog(time.time())
    finally:
        store.finish_refresh(lease, scope=WORKER_LEASE)
