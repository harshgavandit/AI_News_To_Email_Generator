"""Monthly Curiosity Cards upkeep: one report with broken seed links and new incident write-ups.

Runs the seed link check and the postmortem review queue together and writes a single Markdown
report for an editor. It reads the archive (NEWS_DATABASE_URL) and never fetches feeds or edits
cards: an editor reads the queued pages and adds reviewed seeds by hand.

    uv run python -m scripts.curiosity_upkeep --days 35 --report reports/curiosity-upkeep.md

Exits with status 1 when a seed link is broken, so a scheduled run is flagged.
"""
import argparse
import logging
import os
from pathlib import Path

from app.curiosity import postmortem_review_queue
from scripts.check_seed_links import check_seeds, summary as link_summary
from scripts.postmortem_review_queue import render_markdown as queue_markdown

logger = logging.getLogger(__name__)


def review_queue_section(days, limit, store_factory=None):
    """The queue section, or a short note when no archive is configured or it cannot be read."""
    if store_factory is None and not os.getenv("NEWS_DATABASE_URL"):
        return "## Postmortem review queue\n\nSkipped: NEWS_DATABASE_URL is not set for this run.\n"
    try:
        if store_factory is None:
            from app.launch_store import get_store as store_factory
        queue = postmortem_review_queue(store_factory(), days=days, limit=limit)
    except Exception as error:  # A report with the link results is still useful.
        logger.warning("curiosity_upkeep_queue_failed error_type=%s", type(error).__name__)
        return f"## Postmortem review queue\n\nCould not read the archive ({type(error).__name__}).\n"
    return queue_markdown(queue, days).replace("# Postmortem review queue", "## Postmortem review queue", 1)


def usage_section(days, store_factory=None):
    """What opted-in readers opened most: anonymous daily counts summed over the window."""
    if store_factory is None and not os.getenv("NEWS_DATABASE_URL"):
        return ""
    try:
        from datetime import UTC, datetime, timedelta
        if store_factory is None:
            from app.launch_store import get_store as store_factory
        store = store_factory()
        if not store:
            return ""
        since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
        cards = store.curiosity_event_totals(since, events=("card_view", "open_source", "read_next"), limit=10)
        lists = store.curiosity_event_totals(since, group="list_id", limit=5)
    except Exception as error:
        logger.warning("curiosity_upkeep_usage_failed error_type=%s", type(error).__name__)
        return ""
    if not cards and not lists:
        return "## What readers opened\n\nNo anonymous counts yet (readers opt in through audience analytics).\n"
    lines = ["## What readers opened", "", f"Anonymous counts from readers who turned on audience analytics, last {days} days.", ""]
    lines += [f"- `{row['id']}` — {row['count']} opens" for row in cards]
    if lists:
        lines += ["", "Reading lists and lessons:", ""] + [f"- `{row['id']}` — {row['count']} opens" for row in lists]
    return "\n".join(lines) + "\n"


def feedback_section(days, store_factory=None):
    """Reader feedback counts only: messages may hold personal details, so they stay behind /api/admin/feedback."""
    if store_factory is None and not os.getenv("NEWS_DATABASE_URL"):
        return ""
    try:
        from datetime import UTC, datetime, timedelta
        from app import feedback
        if store_factory is None:
            from app.launch_store import get_store as store_factory
        store = store_factory()
        if not store:
            return ""
        rows = feedback.summary(store, (datetime.now(UTC) - timedelta(days=days)).date().isoformat())
    except Exception as error:
        logger.warning("curiosity_upkeep_feedback_failed error_type=%s", type(error).__name__)
        return ""
    if not rows:
        return f"## Reader feedback\n\nNo feedback in the last {days} days.\n"
    totals = {}
    for row in rows:
        totals[row["kind"]] = totals.get(row["kind"], 0) + row["count"]
    useful = {row["page"]: [0, 0] for row in rows if row["kind"] in {"useful", "not_useful"}}
    for row in rows:
        if row["kind"] in {"useful", "not_useful"}:
            useful[row["page"]][row["kind"] == "not_useful"] += row["count"]
    lines = ["## Reader feedback", "", f"Last {days} days. Read the messages at `GET /api/admin/feedback` with the owner key.", ""]
    lines += [f"- {kind}: {count}" for kind, count in sorted(totals.items())]
    if useful:
        lines += ["", "Was this page useful? (yes / no)", ""] + [f"- `{page}`: {yes} / {no}" for page, (yes, no) in sorted(useful.items())]
    return "\n".join(lines) + "\n"


def feature_usage_section(days, store_factory=None):
    """How often readers open a story's details and ask about it (anonymous, opted-in readers only)."""
    if store_factory is None and not os.getenv("NEWS_DATABASE_URL"):
        return ""
    try:
        from datetime import UTC, datetime, timedelta
        from app import feature_usage
        if store_factory is None:
            from app.launch_store import get_store as store_factory
        store = store_factory()
        if not store:
            return ""
        counts = feature_usage.totals(store, (datetime.now(UTC) - timedelta(days=days)).date().isoformat())
    except Exception as error:
        logger.warning("curiosity_upkeep_feature_usage_failed error_type=%s", type(error).__name__)
        return ""
    opened = counts.get(("story_dossier", "open"), 0)
    asked = counts.get(("story_ask", "question"), 0)
    milestones = "\n".join([
        "## Reader milestones", "",
        f"Anonymous counts from browser opt-ins in the last {days} days. These are event totals, not a linked cohort.", "",
        *[f"- {label}: {counts.get(('reader_milestone', action), 0)}" for action, label in [
            ("first_visit", "First visit"), ("first_story", "First story opened"), ("first_follow", "First follow"),
            ("first_brief", "First brief prepared"), ("return_7d", "First return within seven days")]],
        "",
    ])
    if not opened and not asked:
        return milestones + f"\n## Ask about this story\n\nNo counts in the last {days} days (readers opt in through audience analytics).\n"
    answered = counts.get(("story_ask", "answered"), 0)
    share = lambda part, whole: f"{part / whole:.0%}" if whole else "n/a"  # noqa: E731
    return milestones + "\n" + "\n".join([
        "## Ask about this story", "",
        f"Anonymous counts from readers who turned on audience analytics, last {days} days.", "",
        f"- Story details opened: {opened}",
        f"- \"Ask about this story\" opened: {counts.get(('story_ask', 'open'), 0)} ({share(counts.get(('story_ask', 'open'), 0), opened)} of story details)",
        f"- Questions asked: {asked} ({share(asked, opened)} of story details)",
        f"- Answered with sources: {answered} ({share(answered, asked)} of questions); "
        f"not answerable from the sources: {counts.get(('story_ask', 'unanswered'), 0)}; errors: {counts.get(('story_ask', 'error'), 0)}",
        "",
        "Rule of thumb: if questions stay under about 5% of story details, keep the feature where it is; "
        "if they are well above that and mostly answered, make it more visible (a link on story cards, Ctrl+K).",
    ]) + "\n"


def build_report(link_results, queue_section, usage=""):
    return "\n".join([
        "# Curiosity Cards upkeep", "",
        "1. Fix or remove every **broken** link below. Recheck **unreachable** ones before acting.",
        "2. Read the queued write-ups; add the two or three best as reviewed seeds, written only from the page.", "",
        link_summary(link_results).replace("## Curiosity seed links", "## Seed links", 1),
        queue_section,
        usage,
    ]).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=35, help="How far back the review queue looks (1-180).")
    parser.add_argument("--limit", type=int, default=30, help="Most queued write-ups (1-200).")
    parser.add_argument("--report", type=Path, help="Write the report here as well as printing it.")
    args = parser.parse_args(argv)
    results = check_seeds()
    days = max(1, min(args.days, 180))
    report = build_report(results, review_queue_section(days, max(1, min(args.limit, 200))),
                          usage_section(days) + feature_usage_section(days) + feedback_section(days))
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    return 1 if any(row["result"] == "broken" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
