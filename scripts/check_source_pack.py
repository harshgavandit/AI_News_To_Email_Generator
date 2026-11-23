"""Validate a proposed reviewed source pack before enabling it.

Run against a local JSON candidate list. Reports transport, parsed items and recent
entries. A working feed with no entries in 90 days is "quiet", not broken, and can still
be promoted; only feeds that cannot be fetched or parsed are rejected. Never edits the
production catalog or submits URLs to the application. Use --promote only after
reviewing the report and publishers.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import threading
import time

from app.news import read_feed
from app.article_language import article_language, excerpt_language, is_english_article
from app.sources import DEFAULT_SOURCES, Source, load_source_pack, validate_source
from urllib.parse import urlsplit


# Release titles ("v2.4.1"), video and podcast titles are often too short for language
# detection, so those feeds rely on the reviewed language of the project or channel.
LANGUAGE_FROM_REVIEW = {"release"}
LANGUAGE_FROM_REVIEW_KINDS = {"video", "podcast"}


def detection_is_reliable(source):
    return source.coverage not in LANGUAGE_FROM_REVIEW and source.kind not in LANGUAGE_FROM_REVIEW_KINDS


# Version titles ("v2.4.1", "1.18.0-rc.2") are noise to a language detector, so release
# feeds take their language from the review of the project rather than from detection.
TRUSTED_COVERAGE = {"release"}
REVIEWED_ENGLISH = Path(__file__).resolve().parents[1] / "docs" / "research" / "english-reviewed.json"


def reviewed_english(path=REVIEWED_ENGLISH):
    """Ids a reviewer read and confirmed as English publications whose short titles fool detection."""
    if not path.exists():
        return set()
    return {row["id"] for row in json.loads(path.read_text(encoding="utf-8"))}


def english_enough(source, recent, english, other_languages, *, reviewed=False):
    """Accept a reviewed English feed when detection broadly agrees with the review.

    Short headlines make a detector misfire occasionally, so one stray result no longer
    rejects a feed. Promoted article feeds also set require_english, which drops any
    non-English item at ingestion, so a feed confirmed by hand still never shows a
    confidently foreign headline.
    """
    if reviewed or source.coverage in TRUSTED_COVERAGE:
        return True
    if not detection_is_reliable(source):
        return other_languages * 5 <= recent  # At most 20% confidently non-English.
    return english * 5 >= recent * 3 and other_languages * 10 <= recent


# Informa AI keeps a broad directory: a reachable, parseable feed is worth listing even when
# its publisher has been quiet. Only a feed that cannot be fetched or parsed is rejected.
PROMOTABLE = {"active", "quiet"}


def feed_status(state, recent):
    if not state.get("available"):
        return "unavailable"
    return "active" if recent else "quiet"


def requires_english(row):
    return row.get("coverage") not in LANGUAGE_FROM_REVIEW and row.get("kind") not in LANGUAGE_FROM_REVIEW_KINDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--promote", type=Path)
    parser.add_argument("--recheck-existing", action="store_true")
    args = parser.parse_args()
    candidates = json.loads(args.input.read_text(encoding="utf-8"))
    existing_ids = {source.id for source in DEFAULT_SOURCES}
    existing_urls = {source.url for source in DEFAULT_SOURCES}
    confirmed_english = reviewed_english()
    gates = {}
    for row in candidates:
        gates.setdefault(urlsplit(row["url"]).hostname, threading.Semaphore(2))

    def check(row):
        started = time.monotonic()
        result = {"id": row["id"], "url": row["url"]}
        if not args.recheck_existing and (row["id"] in existing_ids or row["url"] in existing_urls):
            return dict(result, status="already_integrated")
        try:
            source = Source(**{key: tuple(value) if key in {"hosts", "article_paths", "excluded_paths", "sitemap_paths"}
                              else value for key, value in row.items()})
            validate_source(source)
            english_feed = source.language.casefold().split("-", 1)[0] == "en"
            if source.id not in existing_ids and not english_feed:
                return dict(result, status="language_excluded", language=source.language)
            with gates[urlsplit(row["url"]).hostname]:
                items, state = read_feed(source)
            cutoff = datetime.now(UTC) - timedelta(days=90)
            recent = [item for item in items if cutoff <= datetime.fromisoformat(item["published_at"]) <= datetime.now(UTC)]
            # A working feed with nothing new is quiet, not broken. Its language is judged on
            # whatever entries it has, or on the review when it has none.
            sample = recent or items
            english = sum(is_english_article(item) for item in sample)
            other_languages = sum(any(code not in ("en", "und") for code in
                                       (article_language(item), excerpt_language(item.get("description")))) for item in sample)
            result.update(status=feed_status(state, recent),
                parsed_entries=len(items), recent_entries=len(recent), error=state.get("error"),
                english_entries=english, non_english_entries=other_languages,
                language_basis="entries" if sample else "review",
                english_verified=english_feed and (not sample or english_enough(source, len(sample), english, other_languages,
                                                                                       reviewed=source.id in confirmed_english)),
                latest_published_at=max((item["published_at"] for item in items), default=None),
                sample_urls=[item["url"] for item in recent[:2]],
                seconds=round(time.monotonic() - started, 3))
        except Exception as error:
            result.update(status="invalid_configuration", error=type(error).__name__)
        return result

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(check, candidates))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "results": results}, indent=2), encoding="utf-8")
    if args.promote:
        active = {row["id"] for row in results if row["status"] in PROMOTABLE and row["english_verified"]}
        approved = [{**row, "reviewed_at": datetime.now(UTC).date().isoformat(),
                     **({"require_english": True} if row["id"] not in existing_ids and requires_english(row) else {})}
                    for row in candidates if row["id"] in active]
        args.promote.parent.mkdir(parents=True, exist_ok=True)
        retained = json.loads(args.promote.read_text(encoding="utf-8")) if args.promote.exists() else []
        merged = {row["id"]: row for row in retained}
        merged.update({row["id"]: row for row in approved})
        temporary = args.promote.with_suffix(args.promote.suffix + ".pending")
        temporary.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        load_source_pack(temporary)
        temporary.replace(args.promote)
    print(json.dumps({status: sum(row["status"] == status for row in results) for status in
                      ("active", "quiet", "unavailable", "already_integrated", "invalid_configuration", "language_excluded")}))


if __name__ == "__main__":
    main()
