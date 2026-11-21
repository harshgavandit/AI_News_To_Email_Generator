"""Durable AI usage accounting, cost estimates and an optional daily spend ceiling.

Counters live in the existing quota table (`brief_limits`), so no migration is needed. Rows are
pruned with other quota rows after seven days. Recording never blocks or fails an AI request.
"""
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import select

logger = logging.getLogger(__name__)
PREFIX = "ai-usage"
# USD per million tokens (input, output). Estimates only; override with NEWS_AI_PRICES as JSON.
DEFAULT_PRICES = {
    "gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-nano": (0.10, 0.40), "gpt-5-mini": (0.25, 2.00), "gpt-5": (1.25, 10.00), "gpt-5-nano": (0.05, 0.40),
    "text-embedding-3-small": (0.02, 0.0), "text-embedding-3-large": (0.13, 0.0),
}
BUCKETS = ("calls", "failures", "prompt", "completion")
_spend = {"day": None, "usd": 0.0, "checked": 0.0}
_lock = threading.Lock()


def day():
    return datetime.now(UTC).date().isoformat()


def prices():
    table = dict(DEFAULT_PRICES)
    try:
        override = json.loads(os.getenv("NEWS_AI_PRICES") or "{}")
        table.update({str(name): (float(rate[0]), float(rate[1])) for name, rate in override.items()})
    except (ValueError, TypeError, IndexError, AttributeError):
        logger.warning("ai_prices_invalid")
    return table


def price_for(model):
    table = prices()
    if model in table:
        return table[model]
    # Dated snapshots such as gpt-4o-mini-2024-07-18 use their family price.
    family = max((name for name in table if model.startswith(name + "-")), key=len, default=None)
    return table.get(family)


def estimate(model, prompt_tokens, completion_tokens):
    rate = price_for(model)
    if rate is None:
        return None
    return round((prompt_tokens * rate[0] + completion_tokens * rate[1]) / 1_000_000, 6)


def _store():
    try:
        from app.launch_store import get_store
        return get_store()
    except Exception:
        return None


def record(task, model, prompt_tokens=0, completion_tokens=0, *, ok=True, store=None):
    store = store or _store()
    cost = estimate(model, prompt_tokens, completion_tokens) or 0.0
    with _lock:
        if _spend["day"] == day():
            _spend["usd"] += cost
    if not store:
        return
    from app.launch_store import limits
    now, scope = time.time(), f"{PREFIX}:{day()}:{task[:32]}:{model[:80]}"
    increments = {"calls": 1, "failures": 0 if ok else 1, "prompt": int(prompt_tokens), "completion": int(completion_tokens)}
    try:
        with store.engine.begin() as conn:
            for bucket, amount in increments.items():
                if not amount and bucket != "calls":
                    continue
                stmt = store.insert(limits).values(scope=scope, bucket=bucket, used=amount, touched=now)
                conn.execute(stmt.on_conflict_do_update(index_elements=[limits.c.scope, limits.c.bucket],
                                                        set_={"used": limits.c.used + amount, "touched": now}))
    except Exception as error:
        logger.warning("ai_usage_record_failed type=%s", type(error).__name__)


def summary(store, days=None):
    """Aggregate recorded usage by day, task and model with estimated cost."""
    from app.launch_store import limits
    with store.engine.connect() as conn:
        rows = conn.execute(select(limits.c.scope, limits.c.bucket, limits.c.used)
                            .where(limits.c.scope.startswith(PREFIX + ":"))).all()
    entries = {}
    for scope, bucket, used in rows:
        try:
            _, date, task, model = scope.split(":", 3)
        except ValueError:
            continue
        if days and date not in days:
            continue
        entry = entries.setdefault((date, task, model), {"day": date, "task": task, "model": model,
                                                         **{name: 0 for name in BUCKETS}})
        if bucket in BUCKETS:
            entry[bucket] += used
    result = []
    for entry in sorted(entries.values(), key=lambda row: (row["day"], row["task"], row["model"]), reverse=True):
        entry["estimated_usd"] = estimate(entry["model"], entry["prompt"], entry["completion"])
        result.append(entry)
    return result


def spend_today(store):
    return round(sum(row["estimated_usd"] or 0 for row in summary(store, days={day()})), 6)


def daily_budget():
    try:
        value = float(os.getenv("NEWS_AI_DAILY_BUDGET_USD", "0") or 0)
    except ValueError:
        return 0.0
    return max(0.0, value)


def within_budget():
    """True unless a daily USD ceiling is configured and today's estimated spend has reached it."""
    budget = daily_budget()
    if not budget:
        return True
    now = time.monotonic()
    with _lock:
        fresh = _spend["day"] == day() and now - _spend["checked"] < 60
        if fresh:
            return _spend["usd"] < budget
    store = _store()
    if not store:
        return True
    try:
        spent = spend_today(store)
    except Exception:
        return True  # Accounting outages must not take AI features down.
    with _lock:
        _spend.update(day=day(), usd=spent, checked=now)
    return spent < budget
