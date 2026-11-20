from datetime import UTC, datetime, timedelta
import pytest
from app.launch_store import Store

from app.curiosity import (
    build_curiosity_cards,
    curiosity_article,
    is_curiosity_candidate,
    curiosity_score,
)


def test_curated_collection_includes_requested_google_research_and_engineering_links():
    expected = {
        "google-monorepo-2016": "https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/",
        "anthropic-opus-4-6": "https://www.anthropic.com/news/claude-opus-4-6",
        "anthropic-long-context": "https://www.anthropic.com/news/prompting-long-context",
        "openai-gpt-4-1-prompting": "https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide",
        "flash-attention-eli5": "https://gordicaleksa.medium.com/eli5-flash-attention-5c44017022ad",
        "attention-is-all-you-need": "https://research.google/pubs/attention-is-all-you-need/",
        "google-file-system": "https://research.google/pubs/the-google-file-system/",
        "google-mapreduce": "https://research.google/pubs/mapreduce-simplified-data-processing-on-large-clusters/",
        "google-bigtable": "https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/",
        "google-spanner": "https://research.google/pubs/spanner-googles-globally-distributed-database-2/",
        "anthropic-source-control": "https://www.anthropic.com/research/redesigning-source-control",
        "openai-performance-factory": "https://openai.com/index/how-openai-performance-factory-keeps-chatgpt-fast/",
        "meta-template-driven-ml": "https://engineering.fb.com/2026/11/18/ml-applications/design-once-deploy-at-scale-template-driven-ml-ecosystem/",
        "openai-postgres-chatgpt": "https://openai.com/index/scaling-postgresql/",
        "uber-artifact-storage": "https://www.uber.com/us/en/blog/modernizing-artifact-storage/",
        "netflix-live-operations": "https://netflixtechblog.com/the-human-infrastructure-how-netflix-built-the-operations-layer-behind-live-at-scale-33e2a311c597",
    }

    cards = {ident: curiosity_article(ident) for ident in expected}

    assert {ident: card["url"] for ident, card in cards.items()} == expected
    assert all(card["company"] and card["tags"] and card["read_minutes"] > 0 for card in cards.values())
    assert all(card["description"] for card in cards.values())


def test_curiosity_filter_prefers_technical_insight_and_rejects_promotional_copy():
    article = {
        "id": "real-systems-story",
        "source_id": "github-blog",
        "title": "How we redesigned our build system for 10x more changes",
        "description": ("The engineering team describes the architecture, bottlenecks, and reliability work "
                        "behind a distributed build pipeline used across production repositories. " * 3),
        "url": "https://github.blog/engineering/how-we-redesigned-builds/",
        "published_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "publisher": "GitHub Blog",
    }
    promotional = dict(article, id="promo", title="Introducing our new all-in-one platform",
                       description="Try our new product today. Sign up now for the best developer tools.")

    assert is_curiosity_candidate(article)
    assert curiosity_score(article) > curiosity_score(promotional)
    assert not is_curiosity_candidate(promotional)


def test_curiosity_filter_requires_english_and_a_useful_source_excerpt():
    relevant = {
        "id": "french-story",
        "source_id": "github-blog",
        "title": "Comment nous avons redessiné notre système distribué",
        "description": "Nous expliquons en détail l'architecture et les défis de fiabilité de notre infrastructure.",
        "url": "https://github.blog/engineering/example/",
        "published_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
    }
    thin = dict(relevant, id="thin", title="How we changed infrastructure", description="Short note.")

    assert not is_curiosity_candidate(relevant)
    assert not is_curiosity_candidate(thin)


def test_curiosity_api_returns_source_backed_cards_without_refreshing_publishers(monkeypatch):
    from app import server

    monkeypatch.setattr(server, "get_store", lambda: None)
    monkeypatch.setattr(server, "build_curiosity_cards", lambda store, *, limit: [curiosity_article("google-monorepo-2016")][:limit])
    server._curiosity_cache.clear()

    payload = server.curiosity(limit=4)

    assert len(payload["cards"]) == 1
    card = payload["cards"][0]
    assert card["id"] == "google-monorepo-2016"
    assert card["summary_basis"] == "editorial_source_summary"
    assert card["url"].startswith("https://research.google/")
    assert payload["selection_limit"] == 5


def test_archive_discovery_ranks_and_deduplicates_against_evergreen_seeds(monkeypatch, tmp_path):
    from app import curiosity, web_digest

    store = Store(f"sqlite:///{(tmp_path / 'curiosity.sqlite').as_posix()}")
    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    description = ("The engineering team details the architecture and operational trade-offs of its distributed "
                   "build pipeline, including the reliability work needed to support production repositories. " * 2)
    lower_signal = ("The team explains how it maintains software infrastructure and production processes across "
                    "services used by developers in the organization. " * 3)
    rows = [
        {"id": "duplicate-url", "source_id": "github-blog", "source": "github-blog", "publisher": "GitHub Blog",
         "title": "Google monorepo case study reprinted", "url": "https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/?utm_source=copy",
         "description": description, "published_at": recent, "kind": "engineering", "category": "software"},
        {"id": "unique-systems-story", "source_id": "github-blog", "source": "github-blog", "publisher": "GitHub Blog",
         "title": "How GitHub redesigned a distributed build pipeline", "url": "https://github.blog/engineering/distributed-build-pipeline/",
         "description": description, "published_at": recent, "kind": "engineering", "category": "software"},
        {"id": "lower-signal-story", "source_id": "github-blog", "source": "github-blog", "publisher": "GitHub Blog",
         "title": "How we maintain our infrastructure", "url": "https://github.blog/engineering/maintaining-infrastructure/",
         "description": lower_signal, "published_at": recent, "kind": "engineering", "category": "software"},
    ]
    monkeypatch.setattr(store, "curiosity_candidates", lambda source_ids, **kwargs: rows)
    monkeypatch.setattr(web_digest, "build_digest", lambda articles, *args, **kwargs: {
        "articles": [{"digest_id": item["id"], "summary": item["description"], "summary_basis": "publisher_excerpt"}
                     for item in articles]
    })

    cards = curiosity.build_curiosity_cards(store, limit=len(curiosity.CURATED_CURIOSITY) + 2)
    ids = [card["id"] for card in cards]

    assert ids[:len(curiosity.CURATED_CURIOSITY)] == [card["id"] for card in curiosity.CURATED_CURIOSITY]
    assert ids.count("duplicate-url") == 0
    assert ids[-2:] == ["unique-systems-story", "lower-signal-story"]
    assert cards[-1]["summary_basis"] == "publisher_excerpt"


def test_mailbox_curiosity_write_is_verified_origin_bound_and_limited(monkeypatch, tmp_path):
    from starlette.requests import Request
    from starlette.responses import Response
    from fastapi import HTTPException
    from pydantic import ValidationError
    from app import public_mail

    store = Store(f"sqlite:///{(tmp_path / 'curiosity-mail.sqlite').as_posix()}")
    monkeypatch.setenv("MAIL_SESSION_SECRET", "mail-session-secret-for-curiosity-tests")
    monkeypatch.setattr(public_mail, "required_store", lambda: store)
    monkeypatch.setattr(public_mail, "verified_recipient", lambda request: "reader@example.org")

    def request(origin="https://brief.example.org"):
        headers = [(b"origin", origin.encode())] if origin else []
        return Request({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "PUT", "scheme": "https", "path": "/api/mail/curiosity", "raw_path": b"/api/mail/curiosity",
            "query_string": b"", "headers": headers, "server": ("brief.example.org", 443), "client": ("127.0.0.1", 1)})

    result = public_mail.update_curiosity_selection(
        public_mail.CuriositySelectionBody(article_ids=["attention-is-all-you-need"]), request(), Response())
    mailbox = public_mail.digest_key("mailbox:reader@example.org")
    assert result["curiosity_ids"] == ["attention-is-all-you-need"]
    snapshot = store.curiosity_selection(mailbox)[0]
    assert snapshot["url"] == curiosity_article("attention-is-all-you-need")["url"]
    assert set(snapshot) == {"id", "title", "company", "publisher", "summary", "url", "tags", "read_minutes"}

    with pytest.raises(HTTPException) as wrong_origin:
        public_mail.update_curiosity_selection(public_mail.CuriositySelectionBody(article_ids=[]),
                                               request("https://evil.example"), Response())
    assert wrong_origin.value.status_code == 403
    with pytest.raises(HTTPException) as unknown:
        public_mail.update_curiosity_selection(public_mail.CuriositySelectionBody(article_ids=["unknown-card"]),
                                               request(), Response())
    assert unknown.value.status_code == 422
    with pytest.raises(ValidationError):
        public_mail.CuriositySelectionBody(article_ids=[f"unknown-{index}" for index in range(6)])

    monkeypatch.setenv("PUBLIC_EMAIL_ENABLED", "1")
    monkeypatch.setenv("MY_EMAIL", "sender@example.org")
    monkeypatch.setenv("APP_PASSWORD", "test-only")
    monkeypatch.setenv("NEWS_DATABASE_URL", "sqlite:///test")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://brief.example.org")
    monkeypatch.setattr(public_mail, "get_store", lambda: store)
    monkeypatch.setattr(public_mail, "verified_recipient", lambda request: "reader@example.org")
    private_config = public_mail.config(request(), Response())
    assert private_config["curiosity_ids"] == ["attention-is-all-you-need"]
    assert private_config["curiosity_selection_limit"] == 5
    monkeypatch.setattr(public_mail, "verified_recipient", lambda request: None)
    public_config = public_mail.config(request(), Response())
    assert "curiosity_ids" not in public_config and "curiosity_selection_limit" not in public_config

    with pytest.raises(HTTPException) as anonymous:
        public_mail.update_curiosity_selection(public_mail.CuriositySelectionBody(article_ids=[]), request(), Response())
    assert anonymous.value.status_code == 401


def test_curated_seed_can_be_added_to_a_manual_brief_without_archive_row(monkeypatch, tmp_path):
    from app import server

    store = Store(f"sqlite:///{(tmp_path / 'curiosity-brief.sqlite').as_posix()}")
    body = server.DigestRequest(pinned_ids=["google-monorepo-2016"])
    observed = {}

    def capture(articles, name, focus, **kwargs):
        observed["articles"] = articles
        observed["pinned_ids"] = kwargs["pinned_ids"]
        return {"articles": [{"title": item["title"], "summary": item["description"], "url": item["url"]}
                             for item in articles]}

    monkeypatch.setattr(server, "select_candidates", lambda pool, focus, count, sources: [])
    monkeypatch.setattr(server, "build_digest", capture)
    digest = server.prepare_digest(body, store, "Reader", "", False, None)

    assert observed["pinned_ids"] == ["google-monorepo-2016"]
    assert digest["articles"][0]["title"] == "Why Google Stores Billions of Lines of Code in a Single Repository"
    assert digest["articles"][0]["summary"]
    assert digest["articles"][0]["url"] == curiosity_article("google-monorepo-2016")["url"]


def test_new_english_curiosity_feeds_reject_non_english_items_at_ingest(tmp_path):
    store = Store(f"sqlite:///{(tmp_path / 'curiosity-language.sqlite').as_posix()}")
    now = datetime.now(UTC).isoformat()
    english = ("The team describes the software architecture and infrastructure behind a scalable production system. "
               "The article explains the operational trade-offs, reliability improvements, deployment process, and "
               "lessons from engineering a global technology service for developers and users around the world. " * 3)
    french = ("L'équipe décrit l'architecture logicielle et l'infrastructure derrière un système de production "
              "évolutif. Cet article explique les compromis opérationnels, les améliorations de fiabilité, le "
              "processus de déploiement et les leçons de conception d'un service technologique mondial. " * 3)
    rows = [
        {"id": "english-curiosity-entry", "title": "How we scaled our production database architecture",
         "description": english, "url": "https://gordicaleksa.medium.com/english-case-study",
         "source": "medium", "publisher": "Aleksa Gordić on Medium", "kind": "engineering",
         "category": "software", "published_at": now},
        {"id": "foreign-curiosity-entry", "title": "Comment nous avons conçu notre infrastructure distribuée",
         "description": french, "url": "https://gordicaleksa.medium.com/foreign-case-study",
         "source": "medium", "publisher": "Aleksa Gordić on Medium", "kind": "engineering",
         "category": "software", "published_at": now},
    ]

    store.ingest("medium-gordicaleksa", rows, True)

    stored = store.pinned_articles([row["id"] for row in rows])
    assert [row["id"] for row in stored] == ["english-curiosity-entry"]
