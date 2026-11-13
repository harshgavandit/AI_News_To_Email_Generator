"""Automated daily morning delivery scheduler for subscribed mailboxes."""
from datetime import UTC, datetime, timedelta
import os
import secrets
import time
import zoneinfo

from app import public_mail
from app.launch_store import get_store


def next_morning(timezone_str: str, dt: datetime | None = None) -> float:
    """Calculate the UTC timestamp for 8:00 AM in the given local timezone."""
    tz = zoneinfo.ZoneInfo(timezone_str)
    if dt is None:
        dt = datetime.now(UTC)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    local_dt = dt.astimezone(tz)
    # Check if 8 AM local time today is still in the future
    today_eight = datetime(local_dt.year, local_dt.month, local_dt.day, 8, 0, 0, tzinfo=tz)
    if today_eight > local_dt:
        return today_eight.astimezone(UTC).timestamp()

    # Otherwise next day at 8 AM local time
    next_day = local_dt.date() + timedelta(days=1)
    next_eight = datetime(next_day.year, next_day.month, next_day.day, 8, 0, 0, tzinfo=tz)
    return next_eight.astimezone(UTC).timestamp()


def unsubscribe_token_for(mailbox: str) -> str:
    """Create a tamper-proof unsubscribe token for a mailbox."""
    return public_mail.seal("unsubscribe", mailbox, 180 * 86400)


def build_unsubscribe_url(mailbox: str) -> str:
    token = unsubscribe_token_for(mailbox)
    origin = os.getenv("PUBLIC_ORIGIN", "https://brief.example.org").rstrip("/")
    return f"{origin}/api/mail/unsubscribe/{token}"


def run_due_subscriptions(generate_fn):
    """Run due morning briefs for active subscriptions with atomic claiming and retry safety."""
    store = get_store()
    if not store:
        return {"sent": 0, "unconfirmed": 0}

    now = time.time()
    due = store.due_subscriptions(now)
    sent = 0
    unconfirmed = 0

    for sub in due:
        mailbox = sub["mailbox"]
        # Claim atomically so concurrent workers do not double-send
        if not store.claim_subscription(mailbox, now, lease_time=180):
            continue

        email = sub["email"]
        tz_str = sub["timezone"]
        next_run = next_morning(tz_str, datetime.now(UTC))
        unsub_url = build_unsubscribe_url(mailbox)

        try:
            brief = generate_fn()
            ident = secrets.token_urlsafe(24)
            public_mail.send_message(
                email,
                "Your Daily World Tech Brief",
                brief["markdown"],
                brief["html"],
                ident,
                unsubscribe_url=unsub_url,
            )
            store.reschedule_subscription(mailbox, next_run)
            sent += 1
        except (OSError, Exception) as exc:
            # Ambiguous transport error or failure: prevent duplicate by rescheduling to next morning
            unconfirmed += 1
            store.reschedule_subscription(mailbox, next_run)

    return {"sent": sent, "unconfirmed": unconfirmed}
