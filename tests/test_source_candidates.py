import json

import pytest

from app.sources import DEFAULT_SOURCES, Source, validate_source
from scripts import promote_sources

PACK = "docs/research/source-candidates-2026-11-21.json"


def load_rows():
    with open(PACK, encoding="utf-8") as handle:
        return json.load(handle)


def test_candidate_pack_is_valid_new_and_english():
    rows = load_rows()
    by_id = {source.id: source.url for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    with open("docs/research/source-candidates-2026-11-21-recheck.json", encoding="utf-8") as handle:
        rechecked = {row["id"]: row["url"] for row in json.load(handle)}
    assert len(rows) >= 150
    assert len({row["id"] for row in rows}) == len(rows) and len({row["url"] for row in rows}) == len(rows)
    for row in rows:
        # Either still a candidate, or promoted under the same id (unchanged, or corrected in the recheck pack).
        if row["id"] in by_id:
            assert by_id[row["id"]] in (row["url"], rechecked.get(row["id"]))
        else:
            assert row["url"].rstrip("/") not in known_urls
        assert row["language"] == "en" and row["url"].startswith("https://")
        validate_source(Source(**{key: tuple(value) if key in {"hosts", "article_paths"} else value
                                  for key, value in row.items()}))


def test_candidate_pack_covers_each_requested_area():
    rows = load_rows()
    kinds = {row["kind"] for row in rows}
    topics = {row["topic"] for row in rows}
    assert {"news", "engineering", "research", "video", "podcast"} <= kinds
    assert {"ai", "software", "security", "startups", "chips", "industry"} <= topics
    assert sum(row["coverage"] == "release" for row in rows) >= 40
    assert any(row["coverage"] == "preprint" for row in rows)


def test_promotion_adds_only_listed_candidates_and_validates(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text("[]", encoding="utf-8")
    rows = load_rows()
    added = promote_sources.promote(PACK, [rows[0]["id"], rows[1]["id"]], catalog=catalog, today="2026-11-21")
    saved = json.loads(catalog.read_text(encoding="utf-8"))
    assert added == [rows[0]["id"], rows[1]["id"]] and len(saved) == 2
    assert all(row["reviewed_at"] == "2026-11-21" and row["require_english"] for row in saved)
    assert promote_sources.promote(PACK, [rows[0]["id"]], catalog=catalog) == []  # Idempotent.
    with pytest.raises(SystemExit):
        promote_sources.promote(PACK, ["not-a-candidate"], catalog=catalog)


def test_language_policy_trusts_review_for_short_title_feeds_only():
    from types import SimpleNamespace
    from scripts.check_source_pack import english_enough, requires_english
    release = SimpleNamespace(coverage="release", kind="engineering")
    blog = SimpleNamespace(coverage="article", kind="engineering")
    assert english_enough(release, 10, 1, 0) and not english_enough(release, 10, 0, 3)
    assert english_enough(blog, 20, 13, 1) and not english_enough(blog, 20, 11, 0) and not english_enough(blog, 20, 18, 3)
    assert not requires_english({"coverage": "release", "kind": "engineering"})
    assert not requires_english({"coverage": "publisher", "kind": "video"})
    assert requires_english({"coverage": "reporting", "kind": "news"})


def test_english_only_feeds_keep_undetectable_headlines_but_drop_foreign_ones():
    from app.article_language import is_not_foreign_article
    assert is_not_foreign_article({"title": "Bun 1.3", "description": ""})
    assert is_not_foreign_article({"title": "OpenAI releases a new reasoning model for developers", "description": ""})
    assert not is_not_foreign_article({"title": "Le gouvernement français annonce un nouveau plan pour l'intelligence artificielle",
                                       "description": ""})


def test_recheck_pack_is_valid_and_promoted_unchanged():
    with open("docs/research/source-candidates-2026-11-21-recheck.json", encoding="utf-8") as handle:
        rows = json.load(handle)
    by_id = {source.id: source.url for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    assert len(rows) == 50 and len({row["id"] for row in rows}) == 50
    for row in rows:
        if row["id"] in by_id:
            assert by_id[row["id"]] == row["url"]  # Promoted unchanged.
        else:
            assert row["url"].rstrip("/") not in known_urls
        validate_source(Source(**{key: tuple(value) if key in {"hosts", "article_paths"} else value
                                  for key, value in row.items()}))


def test_promoted_release_and_video_sources_do_not_filter_by_detected_language():
    from app.sources import BY_ID
    assert not BY_ID["release-oven-sh-bun"].require_english and not BY_ID["yt-openai"].require_english
    assert BY_ID["engadget"].require_english and BY_ID["engadget"].reviewed_at


def test_a_working_feed_without_recent_posts_is_quiet_and_promotable():
    from scripts.check_source_pack import PROMOTABLE, feed_status
    assert feed_status({"available": True}, recent=[]) == "quiet"
    assert feed_status({"available": True}, recent=[{}]) == "active"
    assert feed_status({"available": False, "error": "feed_not_found"}, recent=[]) == "unavailable"
    assert {"active", "quiet"} == PROMOTABLE


def test_second_wave_pack_is_new_valid_and_never_reproposes():
    with open("docs/research/source-candidates-2026-11-21b.json", encoding="utf-8") as handle:
        wave = json.load(handle)
    earlier = load_rows()
    with open("docs/research/source-candidates-2026-11-21-recheck.json", encoding="utf-8") as handle:
        earlier += json.load(handle)
    tried = {row["id"] for row in earlier} | {row["url"].rstrip("/") for row in earlier}
    promoted = {source.id: source.url for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    assert len(wave) >= 150
    assert len({row["id"] for row in wave}) == len(wave) and len({row["url"] for row in wave}) == len(wave)
    for row in wave:
        assert row["id"] not in tried and row["url"].rstrip("/") not in tried
        # Once promoted, a candidate keeps its id and URL; anything else must be new.
        assert promoted.get(row["id"], row["url"]) == row["url"]
        if row["id"] not in promoted:
            assert row["url"].rstrip("/") not in known_urls
        assert row["language"] == "en" and row["url"].startswith("https://")
        validate_source(Source(**{key: tuple(value) if key in {"hosts", "article_paths"} else value
                                  for key, value in row.items()}))
    coverage = {row["coverage"] for row in wave}
    assert {"release", "status", "advisory", "reporting", "publisher"} <= coverage
    assert {"ai", "software", "security", "chips", "startups", "outages"} <= {row["topic"] for row in wave}
