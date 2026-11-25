"""Copy stories that only the previous production database holds into the current one.

Production moved to a new database on 25 November 2026 while the feed sweeps still wrote to the
old one, so stories collected in between exist only there. This copies the stories published in a
time window that the current archive lacks (and which publisher feeds listed them), and never
changes or removes a story the current archive already has. It is safe to run again.

The run is a dry run unless ``--apply`` is given. Database URLs are read from the environment and
never printed:

    OLD_NEWS_DATABASE_URL  the previous database (read only)
    NEWS_DATABASE_URL      the current production database
"""
import argparse
from datetime import UTC, datetime
import os
import sys

from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError

from app.launch_store import Store, article_feeds, articles

BATCH = 500


def moment(text):
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)


def window_ids(store, since, until):
    """Ids and timestamps of stories in the window. ``published_at`` formats vary, so filter after parsing."""
    floor = (since.replace(hour=0, minute=0, second=0, microsecond=0)).date().isoformat()
    stmt = select(articles.c.id, articles.c.published_at).where(articles.c.published_at >= floor)
    with store.engine.connect() as conn:
        rows = conn.execute(stmt).all()
    selected = set()
    for row in rows:
        try:
            published = moment(row.published_at)
        except ValueError:
            continue
        if since <= published < until:
            selected.add(row.id)
    return selected


def copy_columns(store):
    present = {column["name"] for column in inspect(store.engine).get_columns(articles.name)}
    return [column for column in articles.columns if column.name in present]


def recover(old, new, since, until, *, apply=False):
    new.ensure_discovery_schema()
    available = window_ids(old, since, until)
    missing = sorted(available - window_ids(new, since, until))
    with new.engine.connect() as conn:
        # A story can sit outside the window in the new archive (another timestamp format); keep it.
        known = set()
        for start in range(0, len(missing), BATCH):
            chunk = missing[start:start + BATCH]
            known.update(conn.scalars(select(articles.c.id).where(articles.c.id.in_(chunk))))
    missing = [story for story in missing if story not in known]
    summary = {"in_old": len(available), "missing": len(missing), "copied": 0, "feed_links": 0}
    if not apply or not missing:
        return summary
    columns = copy_columns(old)
    for start in range(0, len(missing), BATCH):
        chunk = missing[start:start + BATCH]
        with old.engine.connect() as conn:
            rows = [dict(row._mapping) for row in conn.execute(select(*columns).where(articles.c.id.in_(chunk)))]
            links = [dict(row._mapping) for row in conn.execute(
                select(article_feeds).where(article_feeds.c.article_id.in_(chunk)))]
        with new.engine.begin() as conn:
            if rows:
                result = conn.execute(new.insert(articles).values(rows).on_conflict_do_nothing())
                summary["copied"] += max(result.rowcount or 0, 0)
            if links:
                result = conn.execute(new.insert(article_feeds).values(links).on_conflict_do_nothing())
                summary["feed_links"] += max(result.rowcount or 0, 0)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", required=True, help="ISO time, e.g. 2026-11-23T12:00:00Z")
    parser.add_argument("--until", default="", help="ISO time; defaults to now")
    parser.add_argument("--apply", action="store_true", help="copy the stories (otherwise only count them)")
    args = parser.parse_args(argv)
    old_url, new_url = os.getenv("OLD_NEWS_DATABASE_URL"), os.getenv("NEWS_DATABASE_URL")
    if not old_url or not new_url:
        print("::error::Set both OLD_NEWS_DATABASE_URL (previous database) and NEWS_DATABASE_URL (production).")
        return 1
    if old_url == new_url:
        print("::error::OLD_NEWS_DATABASE_URL and NEWS_DATABASE_URL are the same database; nothing to recover.")
        return 1
    since = moment(args.since)
    until = moment(args.until) if args.until else datetime.now(UTC)
    if since >= until:
        print("::error::--since must be earlier than --until.")
        return 1
    try:
        summary = recover(Store(old_url), Store(new_url), since, until, apply=args.apply)
    except OperationalError as error:
        if "quota" in str(error).lower():
            print("::error::A database has used up its plan quota (most likely the old one). Nothing was copied; "
                  "run this again after its quota resets or the plan limit is raised.")
        else:
            print(f"::error::Could not connect to one of the databases ({type(error).__name__}). Nothing was copied.")
        return 1
    mode = "copied" if args.apply else "dry run"
    line = (f"Recovery ({mode}) {since.isoformat()} to {until.isoformat()}: {summary['in_old']} stories in the old "
            f"database, {summary['missing']} missing from production, {summary['copied']} copied, "
            f"{summary['feed_links']} feed links copied.")
    print(line)
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
