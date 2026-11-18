"""Automated daily morning delivery scheduler for subscribed mailboxes."""
from datetime import UTC, datetime, timedelta
from html import escape
import logging
import os
import smtplib
import time
import zoneinfo

from app import public_mail
from app.brand import DAILY_SUBJECT
from app.launch_store import get_store
from app.mail_capacity import batch_sender, mail_capacity
from app.web_digest import public_site, safe_email_html, safe_href

logger = logging.getLogger(__name__)


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
    return f"{public_site()}/api/mail/unsubscribe/{token}"


def with_unsubscribe(brief, url, *, scheduled=False):
    url = safe_href(url)
    if "introduction" in brief and "articles" in brief:
        html = safe_email_html(brief, url, scheduled=scheduled)
    else:
        # Older stored messages may carry only the rendered formats.
        link = f'<p><a href="{escape(url, quote=True)}">Unsubscribe from morning briefs</a></p>'
        html = brief["html"]
        html = html.replace("</body>", f"{link}</body>") if "</body>" in html else html + link
    return dict(brief, html=html, markdown=f'{brief["markdown"]}\n\nUnsubscribe: {url}')


def personalized_morning_brief(store, mailbox, fallback, load_events):
    from app import ai_insights, radar_store
    followed_only = False
    try:
        saved = radar_store.profiles(store, [mailbox]).get(mailbox)
        if not saved:
            return fallback
        followed_only = saved.get("delivery_mode") == "material_updates"
        profile = ai_insights.RadarProfile.model_validate(saved)
        seen = radar_store.histories(store, [mailbox]).get(mailbox, {})
        result = ai_insights.catchup(store, profile, seen, hours=24, allow_generate=False,
                                     pool=load_events(), followed_only=followed_only)
        if result.get("brief"):
            return result["brief"]
        if result["status"] in {"empty", "caught_up"}:
            return None
    except Exception as error:
        logger.warning("radar_mail_fallback error_type=%s", type(error).__name__)
        if followed_only:
            return None
    return fallback


def morning_event_loader(store):
    from functools import lru_cache
    from app import event_intelligence

    @lru_cache(maxsize=1)
    def load():
        return event_intelligence.catalog(store, hours=24, limit=160)

    return load


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
    load_events = morning_event_loader(store)
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
        content = personalized_morning_brief(store, mailbox, brief, load_events)
        if content is None:
            store.reschedule_subscription(mailbox, next_run)
            continue
        history = content.get("_catchup")
        policies = [(f"mail:{mailbox}", day, 3), *mail_capacity().policies(day, "digests")]
        state, _ = store.reserve_delivery(ident, policies,
            **({"event_mailbox": mailbox, "event_history": history} if history else {}))
        if state != "new":
            store.reschedule_subscription(mailbox, next_run)
            continue
        # Advance before contacting the provider so a timeout is never replayed.
        store.reschedule_subscription(mailbox, next_run)
        if not store.subscription(mailbox)["enabled"]:
            continue
        message = with_unsubscribe(content, unsub_url, scheduled=True)
        try:
            accepted = public_mail.send_message(
                email,
                DAILY_SUBJECT,
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
