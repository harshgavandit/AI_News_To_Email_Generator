from datetime import UTC, datetime
import json

from app.article_language import article_language
from app.briefing import build_briefing
from app.coverage import public_article
from app.launch_store import Store
from scripts import check_source_pack


ENGLISH = "South African data centres expand capacity to meet rising demand"
FRENCH = "Les centres de données français renforcent leurs capacités pour répondre à la demande"


def test_archive_exposes_detected_language_across_publisher_regions(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'articles.db'}")
    base = {"source": "techcentral-za", "publisher": "TechCentral", "kind": "news", "category": "",
            "published_at": datetime.now(UTC).isoformat(), "description": ""}
    items = [dict(base, id="en-story", url="https://techcentral.co.za/english/", title=ENGLISH),
             dict(base, id="fr-story", url="https://techcentral.co.za/french/", title=FRENCH)]
    store.ingest("the-verge", items, True)
    assert public_article(store.article("en-story"))["language"] == "en"
    assert public_article(store.article("fr-story"))["language"] == "fr"
    assert article_language({"title": "v2.0.7"}) == "und"
    assert article_language({"title": "新型ＧＰＵと半導体市場"}) == "ja"

    brief = build_briefing([store.article("fr-story"), store.article("en-story")], limit=1)
    assert [row["id"] for row in brief["articles"]] == ["en-story"]

    store.ingest("techcentral-za", [dict(items[0], id="new-en"), dict(items[1], id="new-fr")], True)
    assert store.article("new-en") is not None
    assert store.article("new-fr") is None
    assert store.source_state()["techcentral-za"]["count"] == 1


def test_feed_promotion_checks_content_and_preserves_legacy_entries(tmp_path, monkeypatch):
    legacy = dict(id="legacy-fr", group="legacy-fr", label="Legacy", kind="news", language="fr",
                  url="https://legacy.example/feed", hosts=["legacy.example"])
    entries = [
        dict(legacy, id=slug, group=slug, label=slug, language=language,
             url=f"https://{slug}.example/feed", hosts=[f"{slug}.example"])
        for slug, language in [("new-en", "en"), ("mislabeled-en", "en"), ("new-fr", "fr")]
    ]
    candidates, report, catalog = (tmp_path / name for name in ("candidates.json", "report.json", "catalog.json"))
    candidates.write_text(json.dumps(entries))
    catalog.write_text(json.dumps([legacy]))

    def fixture_feed(source):
        assert source.id != "new-fr"
        title = ENGLISH if source.id == "new-en" else FRENCH
        return [{"title": title, "published_at": datetime.now(UTC).isoformat(),
                 "url": f"https://{source.id}.example/a"}], {"available": True}

    monkeypatch.setattr(check_source_pack, "read_feed", fixture_feed)
    monkeypatch.setattr("sys.argv", ["check_source_pack", str(candidates), "--report", str(report), "--promote", str(catalog)])
    check_source_pack.main()
    results = {row["id"]: row for row in json.loads(report.read_text())["results"]}
    assert results["new-fr"]["status"] == "language_excluded"
    assert results["mislabeled-en"]["english_entries"] == 0
    assert results["new-en"]["english_verified"]
    saved = json.loads(catalog.read_text())
    assert [row["id"] for row in saved] == ["legacy-fr", "new-en"]
    assert saved[1]["require_english"]
