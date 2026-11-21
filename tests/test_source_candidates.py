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
    known_ids = {source.id for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    assert len(rows) >= 150
    assert len({row["id"] for row in rows}) == len(rows) and len({row["url"] for row in rows}) == len(rows)
    for row in rows:
        assert row["id"] not in known_ids and row["url"].rstrip("/") not in known_urls
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
