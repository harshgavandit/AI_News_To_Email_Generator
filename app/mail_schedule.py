"""Automated daily morning delivery scheduler for subscribed mailboxes."""
from datetime import UTC, datetime, timedelta
from html import escape
import os
import smtplib
import time
import zoneinfo

from app import public_mail
from app.launch_store import get_store
from app.mail_capacity import batch_sender, mail_capacity


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


def with_unsubscribe(brief, url):
    link = f'<p><a href="{escape(url, quote=True)}">Unsubscribe from morning briefs</a></p>'
    html = brief["html"].replace("</body>", f"{link}</body>")
    return dict(brief, html=html if html != brief["html"] else html + link,
                markdown=f'{brief["markdown"]}\n\nUnsubscribe: {url}')


def run_due_subscriptions(generate_fn):
    """Run due morning briefs for active subscriptions with atomic claiming and retry safety."""
    store = get_store()
    if not store:
        return {"sent": 0, "unconfirmed": 0}
    if batch_sender() and os.getenv("MAIL_PILOT_MODE") != "1":
        from app.mail_batches import run_batch_worker
        return run_batch_worker(store, generate_fn)

    now = time.time()
    due = store.due_subscriptions(now)
    if not due:
        return {"sent": 0, "unconfirmed": 0}
    brief = generate_fn()
    sent = 0
    unconfirmed = 0

    for sub in due:
        mailbox = sub["mailbox"]
        # Claim atomically so concurrent workers do not double-send
        if not public_mail.is_pilot_address(sub["email"]) or store.suppressed(mailbox) or not store.claim_subscription(mailbox, now, lease_time=180):
            continue

        email = sub["email"]
        tz_str = sub["timezone"]
        next_run = next_morning(tz_str, datetime.now(UTC))
        unsub_url = build_unsubscribe_url(mailbox)

        ident = public_mail.digest_key(f"daily:{mailbox}:{sub['next_run']}")
        day = public_mail.day()
        state, _ = store.reserve_delivery(ident, [(f"mail:{mailbox}", day, 3), *mail_capacity().policies(day, "digests")])
        if state != "new":
            store.reschedule_subscription(mailbox, next_run)
            continue
        # Advance before contacting the provider so a timeout is never replayed.
        store.reschedule_subscription(mailbox, next_run)
        if not store.subscription(mailbox)["enabled"]:
            continue
        message = with_unsubscribe(brief, unsub_url)
        try:
            accepted = public_mail.send_message(
                email,
                "Your Daily Informa AI",
                message["markdown"],
                message["html"],
                ident,
                unsubscribe_url=unsub_url,
            )
            store.record_delivery(ident, accepted)
            sent += 1
        except (OSError, smtplib.SMTPException):
            # Ambiguous transport error or failure: prevent duplicate by rescheduling to next morning
            unconfirmed += 1

    return {"sent": sent, "unconfirmed": unconfirmed}
