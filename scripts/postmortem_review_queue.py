"""List recent incident write-ups that are not yet Curiosity Cards, for an editor to review.

Reads the configured archive (NEWS_DATABASE_URL, or the local SQLite default) and never fetches a
publisher. Nothing is published: pick the items worth a card, then read each page and add a
reviewed seed to app/curiosity.py.

    uv run python -m scripts.postmortem_review_queue --days 30 --report reports/postmortem-queue.md
"""
import argparse
import json
from pathlib import Path

from app.curiosity import PROBLEM_LABELS, postmortem_review_queue
from app.launch_store import get_store


def render_markdown(queue, days):
    lines = [f"# Postmortem review queue (last {days} days)", "",
             f"{len(queue)} incident write-ups are not yet Curiosity Cards. Read each page before adding a seed.", ""]
    for index, item in enumerate(queue, 1):
        problems = ", ".join(PROBLEM_LABELS.get(problem, problem) for problem in item["problems"])
        lines.append(f"{index}. **{item['title']}** — {item['publisher']}, {item['published_at'] or 'undated'}")
        lines.append(f"   {item['url']}")
        if problems:
            lines.append(f"   Problems: {problems}")
        if item["excerpt"]:
            lines.append(f"   > {item['excerpt']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="How far back to look (1-180 days).")
    parser.add_argument("--limit", type=int, default=40, help="Most items to list (1-200).")
    parser.add_argument("--report", type=Path, help="Write the queue here (.md or .json) as well as printing it.")
    args = parser.parse_args(argv)
    days = max(1, min(args.days, 180))
    queue = postmortem_review_queue(get_store(), days=days, limit=max(1, min(args.limit, 200)))
    text = render_markdown(queue, days)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(queue, indent=2) + "\n" if args.report.suffix == ".json" else text,
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
