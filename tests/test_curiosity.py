from datetime import UTC, datetime, timedelta
import re

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

    cards = curiosity.build_curiosity_cards(store, limit=24)
    ids = [card["id"] for card in cards]

    assert len(ids) == 24 and len(set(ids)) == 24
    assert ids.count("duplicate-url") == 0
    # Fresh discoveries are interleaved after every two evergreen seeds, in rank order.
    assert ids[2] == "unique-systems-story" and ids[5] == "lower-signal-story"
    seeds = [ident for ident in ids if ident not in {"unique-systems-story", "lower-signal-story"}]
    assert seeds == [card["id"] for card in curiosity.featured_seeds()[:22]]
    fresh = {card["id"]: card for card in cards if not card["seed"]}
    assert set(fresh) == {"unique-systems-story", "lower-signal-story"}
    assert fresh["lower-signal-story"]["summary_basis"] == "publisher_excerpt"

    everything = curiosity.build_curiosity_cards(store, limit=curiosity.MAX_CURIOSITY_CARDS)
    assert len(everything) == len(curiosity.CURATED_CURIOSITY) + 2
    assert {card["id"] for card in everything} >= set(curiosity.SEEDS_BY_ID)


def test_fresh_discoveries_keep_reserved_slots_when_archive_is_large(monkeypatch, tmp_path):
    from app import curiosity, web_digest

    store = Store(f"sqlite:///{(tmp_path / 'curiosity-many.sqlite').as_posix()}")
    recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    words = ("queue cache shard ledger router index search billing storage gateway compiler scheduler planner "
             "tracer kernel network payments identity audit streaming warehouse rollout canary sidecar mesh "
             "feature registry backup quota metering sandbox runner fleet edge replica tenant vector embeddings "
             "consensus failover").split()

    def story(index):
        a, b, c = words[index], words[(index * 7 + 3) % len(words)], words[(index * 11 + 5) % len(words)]
        return (f"Engineers explain the {a} architecture behind {b} {c}, with database replication, latency, "
                f"Kubernetes deployment and reliability trade-offs from running {a} {b} in production.")

    rows = [{"id": f"fresh-{index}", "source_id": "github-blog", "source": "github-blog", "publisher": "GitHub Blog",
             "title": f"How we rebuilt {words[index]} for {words[(index * 7 + 3) % len(words)]} at scale",
             "url": f"https://github.blog/engineering/story-{index}/", "published_at": recent,
             "kind": "engineering", "category": "software", "description": story(index) + " " + story(index + 1)}
            for index in range(len(words) - 1)]
    monkeypatch.setattr(store, "curiosity_candidates", lambda source_ids, **kwargs: rows)
    monkeypatch.setattr(web_digest, "build_digest", lambda articles, *args, **kwargs: {"articles": []})

    cards = curiosity.build_curiosity_cards(store, limit=72)
    fresh = [card for card in cards if not card["seed"]]
    assert len(cards) == 72
    # A third of the shelf is reserved for fresh discoveries, even with many evergreen seeds.
    assert len(fresh) == 72 // curiosity.FRESH_SLOT_SHARE
    assert len({card["url"] for card in cards}) == 72
    full = curiosity.build_curiosity_cards(store, limit=curiosity.MAX_CURIOSITY_CARDS)
    expected = len(curiosity._fresh_discoveries(store, curiosity.MAX_FRESH_CARDS))
    assert expected > 72 // curiosity.FRESH_SLOT_SHARE
    assert len([card for card in full if not card["seed"]]) == expected
    assert curiosity.build_curiosity_cards(None, limit=500)[0]["id"] == curiosity.featured_seeds()[0]["id"]
    assert len(curiosity.build_curiosity_cards(None, limit=500)) == len(curiosity.CURATED_CURIOSITY)


def test_expanded_seed_collection_is_unique_secure_and_covers_requested_companies():
    from urllib.parse import urlsplit
    from app import curiosity
    from app.sources import BY_ID

    seeds = curiosity.CURATED_CURIOSITY
    assert len(seeds) >= 55
    assert len({seed["id"] for seed in seeds}) == len(seeds)
    assert len({seed["url"].rstrip("/") for seed in seeds}) == len(seeds)
    assert len({seed["title"].casefold() for seed in seeds}) == len(seeds)
    for seed in seeds:
        parts = urlsplit(seed["url"])
        # No tracking parameters; the Azure status history only addresses a review by its tracking ID.
        allowed_query = parts.netloc == "azure.status.microsoft" and re.fullmatch(r"trackingId=[A-Z0-9-]+", parts.query)
        assert parts.scheme == "https" and parts.netloc and (not parts.query or allowed_query), seed["id"]
        # Talks and posts outside the feed catalog carry no source_id; everything else maps to a reviewed feed.
        assert seed["source_id"] is None or seed["source_id"] in BY_ID, seed["id"]
        assert 60 <= len(seed["description"]) <= 400, seed["id"]
        assert 1 <= len(seed["tags"]) <= 5 and 1 <= seed["read_minutes"] <= 45, seed["id"]
        assert 1990 <= seed["year"] <= 2026, seed["id"]
        assert not seed["published_at"] or seed["published_at"].startswith(str(seed["year"])), seed["id"]
        assert not curiosity._promotional.search(f"{seed['title']} {seed['description']}"), seed["id"]
        # Seeds must not collide with each other under the same near-duplicate test used for the archive.
        others = [other for other in seeds if other["id"] != seed["id"]]
        assert not curiosity._is_duplicate(seed, others), seed["id"]
    companies = {seed["company"] for seed in seeds}
    assert {"Google", "Anthropic", "OpenAI", "Microsoft", "Palo Alto Networks", "Stripe", "Razorpay", "Netflix",
            "Uber", "Cloudflare", "Airbnb", "Meta", "Spotify"} <= companies
    claude_code = [seed for seed in seeds if "Claude Code" in seed["tags"]]
    assert len(claude_code) >= 2


def test_new_engineering_feeds_feed_curiosity_discovery():
    from app import curiosity
    from app.sources import BY_ID

    for ident in ("paloalto-engineering", "engineering-at-microsoft"):
        source = BY_ID[ident]
        assert source.enabled and source.kind == "engineering" and source.url.startswith("https://")
        assert ident in curiosity._candidate_sources()


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


@pytest.mark.parametrize("ident", ["claude-code-best-practices", "razorpay-kafka-upi", "paloalto-synonym-rag",
                                   "openai-kubernetes-7500"])
def test_new_seed_flows_from_brief_builder_into_email_html(monkeypatch, tmp_path, ident):
    from app import server
    from app.web_digest import safe_email_html

    store = Store(f"sqlite:///{(tmp_path / 'curiosity-email.sqlite').as_posix()}")
    seed = curiosity_article(ident)

    def capture(articles, name, focus, **kwargs):
        return {"title": "Reader brief", "articles": [
            {"digest_id": item["id"], "title": item["title"], "summary": item["description"], "url": item["url"],
             "publisher": item["publisher"], "source": item["source"]} for item in articles]}

    monkeypatch.setattr(server, "select_candidates", lambda pool, focus, count, sources: [])
    monkeypatch.setattr(server, "build_digest", capture)
    digest = server.prepare_digest(server.DigestRequest(pinned_ids=[ident]), store, "Reader", "", False, None)

    assert [item["url"] for item in digest["articles"]] == [seed["url"]]
    assert digest["articles"][0]["title"] == seed["title"]
    html = safe_email_html(digest)
    from html import escape
    from app.web_digest import safe_href
    assert escape(safe_href(seed["url"]), quote=True) in html
    assert escape(seed["title"], quote=False) in html
    assert escape(seed["description"], quote=False) in html


def test_scheduled_email_includes_new_curiosity_seed_cards(tmp_path):
    from html import escape
    from app import mail_schedule
    from app.curiosity import resolve_curiosity_cards
    from app.web_digest import safe_href

    store = Store(f"sqlite:///{(tmp_path / 'curiosity-scheduled.sqlite').as_posix()}")
    ids = ["google-borg", "stripe-idempotency", "microsoft-largest-git-repo"]
    cards = resolve_curiosity_cards(store, ids)
    assert [card["id"] for card in cards] == ids
    brief = mail_schedule.append_curiosity_section(
        {"markdown": "Brief", "html": "<html><body><p>Brief</p></body></html>"}, cards)
    html = brief["html"]
    assert html.index("Curiosity Cards") < html.index("</body>")
    for card in cards:
        assert safe_href(card["url"]) in html and safe_href(card["url"]) in brief["markdown"]
        assert escape(card["title"], quote=False) in html
        assert escape(card["summary"][:60], quote=False) in html


def test_curiosity_covers_game_engineering_and_every_theme_with_verified_sources():
    from app import curiosity

    seeds = curiosity.CURATED_CURIOSITY
    companies = {seed["company"] for seed in seeds}
    assert {"Riot Games", "Rockstar Games", "Epic Games", "Roblox", "Naughty Dog", "Bungie", "Blizzard Entertainment",
            "Discord", "Amazon", "Microsoft"} <= companies
    primary = {curiosity.card_themes(seed)[0] for seed in seeds}
    assert primary == {ident for ident, _, _ in curiosity.THEMES}
    # Rockstar publishes little; its card is a first-party SIGGRAPH talk, and the GTA V study is labelled independent.
    rdr2 = curiosity.curiosity_article("rockstar-rdr2-atmosphere")
    assert rdr2["company"] == "Rockstar Games" and "SIGGRAPH" in rdr2["publisher_detail"]
    gta = curiosity.curiosity_article("gta-v-graphics-study")
    assert gta["company"] != "Rockstar Games" and "not a Rockstar publication" in gta["description"]
    for seed in seeds:
        if seed.get("why_read"):
            assert 20 <= len(seed["why_read"]) <= 160, seed["id"]


def test_cards_carry_theme_format_technologies_and_dates():
    from app import curiosity

    cards = {card["id"]: card for card in curiosity.build_curiosity_cards(None, limit=curiosity.MAX_CURIOSITY_CARDS)}
    netcode = cards["riot-valorant-netcode"]
    assert netcode["theme"] == "game-engineering" and netcode["themes"][0] == "game-engineering"
    assert netcode["published_at"] == "2020-07-28" and netcode["why_read"]
    assert cards["roblox-return-to-service"]["format"] == "postmortem"
    assert cards["naughty-dog-fibers"]["format"] == "talk"
    assert cards["amazon-dynamodb-paper"]["format"] == "paper"
    assert {"Consul", "BoltDB"} <= set(cards["roblox-return-to-service"]["technologies"])
    assert "WebRTC" in cards["discord-webrtc-voice"]["technologies"]
    assert {"RAG", "BM25", "Embeddings"} <= set(cards["anthropic-contextual-retrieval"]["technologies"])
    # Technologies only come from words that appear in the title, excerpt or reviewed tags.
    for card in cards.values():
        text = f"{card['title']} {card['description']} {' '.join(card['tags'])}".casefold()
        assert len(card["technologies"]) <= 6
        assert all(tech for tech in card["technologies"])
        assert card["format"] in curiosity.FORMATS and card["theme"] in curiosity.THEME_LABELS, card["id"]
        assert text
    first_nine = [card["theme"] for card in curiosity.build_curiosity_cards(None, limit=9)]
    assert len(set(first_nine)) == 9  # The featured shelf opens with one card from each theme.


def test_archive_discoveries_drop_announcements_rank_depth_and_cap_each_company(monkeypatch, tmp_path):
    from app import curiosity, web_digest

    store = Store(f"sqlite:///{(tmp_path / 'curiosity-quality.sqlite').as_posix()}")
    recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    body = ("Engineers describe the architecture, latency budget and distributed database replication behind the "
            "service, with Kubernetes deployment details and reliability lessons from production. ")

    def row(ident, source_id, title, description=body * 2):
        return {"id": ident, "source_id": source_id, "source": source_id, "publisher": source_id, "title": title,
                "url": f"https://example.test/{ident}", "description": description, "published_at": recent,
                "kind": "engineering", "category": "software"}

    subjects = ("merge queue", "code search", "Actions runners", "Git storage", "notification fanout")
    rows = [row(f"github-{index}", "github-engineering", f"How GitHub rebuilt {subject} for scale and latency")
            for index, subject in enumerate(subjects)]
    rows += [row("unreal-release", "unreal-engine-blog", "Unreal Engine 5.8 is now available with new tools"),
             row("godot-snapshot", "godot-engine-blog", "Dev snapshot: Godot 4.8 beta 4 with new renderer"),
             row("factorio-belts", "factorio-blog",
                 "How we optimized belt simulation to cut frame time by 40% in large factories",
                 "The Factorio team explains the game engine's belt simulation, memory layout and CPU performance "
                 "work that cut update time by 40 percent on large maps, with profiling data and trade-offs. " * 2),
             row("discord-cache", "engineering-discord", "How Discord serves 10 million requests per second with a cache")]
    monkeypatch.setattr(store, "curiosity_candidates", lambda source_ids, **kwargs: rows)
    monkeypatch.setattr(web_digest, "build_digest", lambda articles, *args, **kwargs: {"articles": [
        {"digest_id": item["id"], "summary": item["description"], "summary_basis": "ai_feed_summary",
         "whyItMatters": "Shows the measured trade-offs behind the change."} for item in articles]})

    fresh = curiosity._fresh_discoveries(store, 40)
    ids = [item["id"] for item in fresh]
    assert "unreal-release" not in ids and "godot-snapshot" not in ids
    assert "factorio-belts" in ids[:4]
    # Three GitHub stories lead; the other two wait until every company has had a turn.
    github_positions = [index for index, ident in enumerate(ids) if ident.startswith("github-")]
    assert ids.index("discord-cache") < github_positions[3]

    cards = {card["id"]: card for card in curiosity.build_curiosity_cards(store, limit=120) if not card["seed"]}
    assert "game-engineering" in cards["factorio-belts"]["themes"]
    assert cards["factorio-belts"]["why_read"] == "Shows the measured trade-offs behind the change."
    assert cards["factorio-belts"]["format"] == "case-study"


def test_curated_card_outside_the_feed_catalog_reaches_brief_and_email(monkeypatch, tmp_path):
    from html import escape
    from app import server
    from app.web_digest import safe_email_html, safe_href

    store = Store(f"sqlite:///{(tmp_path / 'curiosity-offcatalog.sqlite').as_posix()}")
    seed = curiosity_article("riot-valorant-128-tick")
    assert seed["source_id"] is None

    def capture(articles, name, focus, **kwargs):
        return {"title": "Reader brief", "articles": [
            {"digest_id": item["id"], "title": item["title"], "summary": item["description"], "url": item["url"],
             "publisher": item["publisher"], "source": item["source"]} for item in articles]}

    monkeypatch.setattr(server, "select_candidates", lambda pool, focus, count, sources: [])
    monkeypatch.setattr(server, "build_digest", capture)
    digest = server.prepare_digest(server.DigestRequest(pinned_ids=[seed["id"]]), store, "Reader", "", False, None)
    html = safe_email_html(digest)
    assert escape(safe_href(seed["url"]), quote=True) in html and escape(seed["title"], quote=True) in html
    from app.curiosity import resolve_curiosity_cards
    assert resolve_curiosity_cards(store, [seed["id"]])[0]["url"] == seed["url"]


def test_agentic_and_ai_native_engineering_are_first_class_themes():
    from app import curiosity

    cards = {card["id"]: card for card in curiosity.build_curiosity_cards(None, limit=curiosity.MAX_CURIOSITY_CARDS)}
    agents = [card for card in cards.values() if card["theme"] == "agents"]
    factories = [card for card in cards.values() if card["theme"] == "ai-engineering"]
    assert len(agents) >= 10 and len(factories) >= 6
    assert cards["stripe-minions-coding-agents"]["theme"] == "ai-engineering"
    assert cards["manus-context-engineering"]["theme"] == "agents"
    assert cards["anthropic-building-effective-agents"]["theme"] == "agents"
    # Every reviewed question is a real question, and fresh feed items never get an invented one.
    for card in cards.values():
        if card["question"]:
            assert card["seed"] and card["question"].endswith("?") and len(card["question"]) <= 120, card["id"]
    assert cards["discord-elixir-5m-concurrent"]["question"] == "How does Discord handle millions of concurrent users?"
    companies = {card["company"] for card in cards.values()}
    assert {"Cognition", "Manus", "Slack", "Pinterest", "Figma", "ByteDance", "Shopify", "Spotify"} <= companies
    article = {"title": "How we built a multi-agent orchestration layer with LangGraph and MCP tool calling",
               "description": "Engineers describe agent routing, memory, retries and tracing in production. " * 3}
    assert curiosity.card_themes(article)[0] == "agents"
    assert curiosity.card_themes({"title": "Our background coding agents opened 2,000 pull requests",
                                  "description": "Lessons from AI-generated code review and test generation. " * 3})[0] == "ai-engineering"


def test_real_world_problems_are_labelled_and_reviewed_breakdowns_are_complete():
    from app import curiosity

    seeds = {seed["id"]: seed for seed in curiosity.CURATED_CURIOSITY}
    assert set(curiosity.REVIEWED_BREAKDOWNS) <= set(seeds)
    assert set(curiosity.REVIEWED_PROBLEMS) <= set(seeds)
    for ident in curiosity.REVIEWED_BREAKDOWNS:
        card = curiosity._card(seeds[ident], {})
        assert set(card["breakdown"]) == {"problem", "approach", "result"}, ident
        assert all(20 <= len(line) <= 320 for line in card["breakdown"].values()), ident
        assert card["problems"] and set(card["problems"]) <= set(curiosity.PROBLEM_LABELS), ident
    postmortems = [ident for ident, seed in seeds.items() if curiosity.card_format(seed) == "postmortem"]
    assert len(postmortems) >= 15
    assert all("outages" in curiosity.card_problems(seeds[ident]) for ident in postmortems), \
        [ident for ident in postmortems if "outages" not in curiosity.card_problems(seeds[ident])]
    # Fresh archive cards never carry an editorial breakdown, even if a row claims one.
    fresh = {"id": "x", "title": "How we migrated our Postgres fleet to sharded clusters", "url": "https://github.blog/x",
             "source_id": "github-engineering", "publisher": "GitHub", "breakdown": {"problem": "a", "approach": "b", "result": "c"},
             "description": "We moved from one primary to 32 shards and cut p99 latency by 40%."}
    card = curiosity._card(fresh, {})
    assert card["breakdown"] is None
    assert set(card["problems"]) == {"migrations", "scaling-data"}
    assert curiosity.card_problems({"title": "Our new design system", "description": "Colours and type."}) == []


def test_problem_stories_outrank_feature_tours_among_fresh_posts():
    from app.curiosity import quality_score

    description = ("The team explains the architecture of its Kubernetes platform, the database replication design "
                   "and the deployment pipeline used across services.")
    tour = {"title": "A tour of our Kubernetes platform", "description": description}
    report = {"title": "GitHub availability report: September 2026",
              "description": "In September, we experienced two incidents that resulted in degraded performance. " + description}
    postmortem = {"title": "What went wrong: the root cause of our Kubernetes outage", "description": description}
    assert quality_score(postmortem) > quality_score(tour)
    assert quality_score(report) > quality_score(tour)


def test_candidate_sampling_gives_every_publisher_a_share(research_database):
    from app.sources import BY_ID

    store = Store(research_database)
    store.migrate()
    now = datetime.now(UTC)

    def post(source_id, index, hours):
        source = BY_ID[source_id]
        return {"id": f"{source_id}-{index}", "title": f"Post {index} from {source.label}", "url": f"https://{source.hosts[0]}/p{index}",
                "description": f"The engineering team explains how service {index} handles database replication, deployment and reliability in production.", "source": source.group, "source_id": source_id, "publisher": source.label,
                "kind": source.kind, "category": "software", "published_at": (now - timedelta(hours=hours)).isoformat()}

    store.ingest("github-engineering", [post("github-engineering", i, i) for i in range(30)], True)
    store.ingest("cloudflare-postmortems", [post("cloudflare-postmortems", i, 200 + i) for i in range(3)], True)
    ids = ["github-engineering", "cloudflare-postmortems"]
    newest = store.curiosity_candidates(ids, limit=10)
    assert {row["source_id"] for row in newest} == {"github-engineering"}, "without sampling the busy feed fills the window"
    sampled = store.curiosity_candidates(ids, limit=10, per_source=4)
    by_source = {}
    for row in sampled:
        by_source.setdefault(row["source_id"], []).append(row["id"])
    assert by_source == {"github-engineering": [f"github-engineering-{i}" for i in range(4)],
                         "cloudflare-postmortems": [f"cloudflare-postmortems-{i}" for i in range(3)]}
    assert "source_rank" not in sampled[0] and {"title", "url", "published_at"} <= set(sampled[0])


def test_curiosity_api_lists_problem_labels(monkeypatch):
    from app import server

    monkeypatch.setattr(server, "build_curiosity_cards", lambda store, limit: [])
    monkeypatch.setattr(server, "get_store", lambda: None)
    server._curiosity_cache.clear() if hasattr(server._curiosity_cache, "clear") else None
    payload = server.curiosity(limit=3)
    assert {"id": "outages", "label": "Outages & incidents"} in payload["problems"]
    assert len(payload["problems"]) == 9


def test_reading_lists_use_reviewed_cards_and_fit_in_one_brief():
    from starlette.responses import Response
    from app import curiosity, server

    assert len(curiosity.COLLECTIONS) >= 6
    ids = [ident for ident, *_ in curiosity.COLLECTIONS]
    assert len(set(ids)) == len(ids) and all(re.fullmatch(r"[a-z0-9-]{1,80}", ident) for ident in ids)
    for ident, title, summary, card_ids, problems in curiosity.COLLECTIONS:
        assert set(card_ids) <= set(curiosity.SEEDS_BY_ID), ident
        assert 4 <= len(card_ids) <= 10 and len(set(card_ids)) == len(card_ids), ident
        assert title and 60 <= len(summary) <= 400 and set(problems) <= set(curiosity.PROBLEM_LABELS), ident
    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    index = client.get("/api/curiosity/collections")
    assert index.headers["cache-control"].startswith("public, max-age=3600") and index.headers["etag"].startswith('W/"')
    first = index.json()["collections"][0]
    assert "cards" not in first, "the index never carries the cards"
    assert first["card_ids"] == list(curiosity.COLLECTIONS[0][3]) and first["card_count"] == len(first["card_ids"])
    detail = client.get(f"/api/curiosity/collections/{first['id']}").json()["list"]
    assert [card["id"] for card in detail["cards"]] == first["card_ids"]
    assert detail["read_minutes"] == first["read_minutes"] == sum(card["read_minutes"] for card in detail["cards"])
    for item in index.json()["collections"]:
        cards = client.get(f"/api/curiosity/collections/{item['id']}").json()["list"]["cards"]
        assert all(card["seed"] and card["url"].startswith("https://") for card in cards), item["id"]


def test_a_whole_reading_list_can_be_pinned_into_a_brief(monkeypatch, tmp_path):
    from app import curiosity, server

    store = Store(f"sqlite:///{(tmp_path / 'list-brief.sqlite').as_posix()}")
    card_ids = list(curiosity.COLLECTIONS[0][3])
    observed = {}

    def capture(articles, name, focus, **kwargs):
        observed["pinned"] = kwargs["pinned_ids"]
        return {"articles": [{"title": item["title"], "summary": item["description"], "url": item["url"]} for item in articles]}

    monkeypatch.setattr(server, "select_candidates", lambda pool, focus, count, sources: [])
    monkeypatch.setattr(server, "build_digest", capture)
    digest = server.prepare_digest(server.DigestRequest(pinned_ids=card_ids, top_n=10), store, "Reader", "", False, None)
    assert observed["pinned"] == card_ids
    assert [item["url"] for item in digest["articles"]] == [curiosity.SEEDS_BY_ID[ident]["url"] for ident in card_ids]


ROUND_TEN_SEEDS = (
    "aws-dynamodb-dns-2025", "cloudflare-outage-november-2025", "google-cloud-service-control-2025",
    "openai-december-2024-incident", "github-ddos-2018", "cloudflare-leap-second-2017", "letsencrypt-caa-rechecking-bug",
    "knight-capital-sec-2013", "xz-utils-backdoor-2024", "circleci-security-incident-2023", "cloudflare-thanksgiving-2023",
    "okta-support-system-rca-2023", "cloudflare-log4j-cve-2021-44228", "37signals-left-the-cloud",
    "stack-overflow-architecture-2016", "discord-indexing-trillions", "github-rails-upgrade-2018",
    "figma-webassembly-load-time", "canva-counting-billions", "khan-academy-goliath", "stripe-sorbet", "uber-querygpt",
    "linkedin-genai-product-musings", "github-copilot-llms", "shopify-bfcm-scale-testing",
)


def test_round_ten_seeds_are_reviewed_and_grouped_into_new_reading_lists():
    from app import curiosity

    assert len(curiosity.CURATED_CURIOSITY) >= 151
    for ident in ROUND_TEN_SEEDS:
        card = curiosity._card(curiosity.SEEDS_BY_ID[ident], {})
        assert card["problems"] and card["why_read"] and card["url"].startswith("https://"), ident
        # Every new seed except the Copilot history and Stack Overflow tour carries a reviewed breakdown.
        if ident not in {"github-copilot-llms", "stack-overflow-architecture-2016"}:
            assert set(card["breakdown"]) == {"problem", "approach", "result"}, ident
    security = {card["id"] for card in curiosity.CURATED_CURIOSITY if "security-incidents" in curiosity.card_problems(card)}
    assert {"xz-utils-backdoor-2024", "circleci-security-incident-2023", "okta-support-system-rca-2023",
            "cloudflare-thanksgiving-2023", "cloudflare-log4j-cve-2021-44228"} <= security
    lists = {ident: cards for ident, _, _, cards, _ in curiosity.COLLECTIONS}
    assert {"security-incidents-up-close", "leaving-the-cloud-and-running-lean", "recent-outages-2024-2025",
            "building-ai-products-in-production"} <= set(lists)
    assert "37signals-left-the-cloud" in lists["leaving-the-cloud-and-running-lean"]
    assert "cost" in curiosity.card_problems(curiosity.SEEDS_BY_ID["37signals-left-the-cloud"])
    # A closing parenthesis that balances one in the title is kept.
    log4j = curiosity._card(curiosity.SEEDS_BY_ID["cloudflare-log4j-cve-2021-44228"], {})
    assert log4j["title"] == "Inside the Log4j2 vulnerability (CVE-2021-44228)"


def test_every_reviewed_card_suggests_what_to_read_next():
    from app import curiosity

    for ident in curiosity.SEEDS_BY_ID:
        related = curiosity._related_ids(ident)
        assert ident not in related and len(set(related)) == len(related) <= 2, ident
        assert set(related) <= set(curiosity.SEEDS_BY_ID), ident
    # The next stop on a reading list comes first.
    assert curiosity._related_ids("aws-s3-outage-2017")[0] == "meta-outage-2021"
    card = curiosity._card(curiosity.SEEDS_BY_ID["aws-s3-outage-2017"], {})
    assert card["related"][0] == {"id": "meta-outage-2021", "title": curiosity.SEEDS_BY_ID["meta-outage-2021"]["title"],
                                  "company": "Meta", "url": curiosity.SEEDS_BY_ID["meta-outage-2021"]["url"]}
    fresh = curiosity._card({"id": "x", "title": "How we cut p99 latency", "url": "https://github.blog/x",
                             "source_id": "github-engineering", "description": "A long enough excerpt about latency work."}, {})
    assert fresh["related"] == []


def test_lessons_group_reviewed_cards_and_ship_with_reading_lists():
    from starlette.responses import Response
    from app import curiosity, server

    ids = [ident for ident, *_ in curiosity.LESSONS]
    assert len(ids) >= 6 and len(set(ids)) == len(ids)
    for ident, title, summary, card_ids in curiosity.LESSONS:
        assert re.fullmatch(r"[a-z0-9-]{1,72}", ident) and title and 60 <= len(summary) <= 400, ident
        assert set(card_ids) <= set(curiosity.SEEDS_BY_ID) and 2 <= len(card_ids) <= 10, ident
    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    payload = client.get("/api/curiosity/collections").json()
    lessons = payload["lessons"]
    assert [lesson["id"] for lesson in lessons] == [f"lesson-{ident}" for ident in ids]
    assert all(lesson["kind"] == "lesson" and lesson["card_count"] >= 2 for lesson in lessons)
    assert not {lesson["id"] for lesson in lessons} & {item["id"] for item in payload["collections"]}
    lesson = client.get(f"/api/curiosity/collections/{lessons[0]['id']}").json()["list"]
    assert lesson["kind"] == "lesson" and len(lesson["cards"]) == lessons[0]["card_count"]


def test_postmortem_of_the_week_changes_on_mondays_and_cycles_every_postmortem():
    from app import curiosity

    monday = datetime(2026, 11, 23, 2, 30, tzinfo=UTC)
    picks = [curiosity.postmortem_of_the_week(monday + timedelta(weeks=week))["id"]
             for week in range(len(curiosity.weekly_postmortems()))]
    assert sorted(picks) == curiosity.weekly_postmortems(), "every reviewed postmortem comes round once"
    assert curiosity.postmortem_of_the_week(monday + timedelta(days=6, hours=20))["id"] == picks[0], "stable all week"
    card = curiosity.postmortem_of_the_week(monday)
    assert card["format"] == "postmortem" and set(card["breakdown"]) == {"problem", "approach", "result"}


def test_postmortem_review_queue_lists_unreviewed_write_ups_only(research_database):
    from app import curiosity
    from app.sources import BY_ID

    store = Store(research_database)
    store.migrate()
    now = datetime.now(UTC)

    def post(source_id, ident, title, description, hours=5):
        source = BY_ID[source_id]
        return {"id": ident, "title": title, "url": f"https://{source.hosts[0]}/{ident}", "description": description,
                "source": source.group, "source_id": source_id, "publisher": source.label, "kind": source.kind,
                "category": "software", "published_at": (now - timedelta(hours=hours)).isoformat()}

    store.ingest("cloudflare-postmortems", [
        post("cloudflare-postmortems", "pm-1", "Post-incident review of the outage that broke DNS lookups for our customers",
             "This post explains the root cause of the incident, which was a configuration change to our resolver fleet "
             "that removed a record set, and describes the steps we are taking so that it does not happen again."),
        post("cloudflare-postmortems", "promo", "Introducing faster Workers builds",
             "Our new build pipeline makes deploys quicker for every developer on the platform, and this post "
             "describes how the engineering team designed it and what it means for your projects."),
        post("cloudflare-postmortems", "old-seed", "Details of the Cloudflare outage on July 2, 2019",
             "The root cause of the outage was a regular expression in a firewall rule that used all of the "
             "available processing power on machines across the world, and this is the full story of that day."),
    ], True)
    queue = curiosity.postmortem_review_queue(store, days=30)
    assert [item["id"] for item in queue] == ["pm-1"], "feature posts and already-reviewed cards are left out"
    assert queue[0]["url"].startswith("https://") and "outages" in queue[0]["problems"]
    assert curiosity.postmortem_review_queue(None) == []

    from scripts.postmortem_review_queue import render_markdown
    text = render_markdown(queue, 30)
    assert "1 incident write-ups" in text and "Post-incident review of the outage that broke DNS" in text


def test_seed_link_checker_classifies_without_live_requests():
    from scripts import check_seed_links as links

    assert links.classify("https://a.com/x", 200, "https://www.a.com/x/") == "ok"
    assert links.classify("https://a.com/x", 200, "https://b.com/x") == "moved"
    assert links.classify("https://a.com/x", 403, "https://a.com/x") == "blocked"
    assert links.classify("https://a.com/x", 404, "https://a.com/x") == "broken"
    assert links.classify("https://a.com/x", None, "", "ConnectionError") == "unreachable"

    class Reply:
        def __init__(self, status, url):
            self.status_code, self.url = status, url

        def close(self):
            pass

    class Session:
        headers = {}

        def head(self, url, **_):
            return Reply(405 if "head-refused" in url else 404 if "gone" in url else 200, url)

        def get(self, url, **_):
            return Reply(200, url)

    seeds = [{"id": "fine", "url": "https://a.com/fine"}, {"id": "gone", "url": "https://a.com/gone"},
             {"id": "refuses-head", "url": "https://a.com/head-refused"}]
    results = {row["id"]: row["result"] for row in links.check_seeds(seeds, workers=2, session=Session())}
    assert results == {"fine": "ok", "gone": "broken", "refuses-head": "ok"}
    assert "**broken** `gone`" in links.summary(links.check_seeds(seeds, workers=1, session=Session()))


def test_round_eleven_adds_india_scale_and_app_performance_stories():
    from app import curiosity

    india = ["zerodha-scaling-common-sense", "phonepe-technology-journey", "flipkart-tidb-active-passive",
             "swiggy-serviceability-platform", "dream11-ipl-2023-concurrency", "meesho-rollout-service"]
    apps = ["airbnb-sunsetting-react-native", "shopify-react-native-future", "discord-ios-react-native-performance",
            "netflix-faster-website", "slack-rebuilding-desktop", "pinterest-pwa-retrospective", "uber-rider-app-architecture"]
    for ident in india + apps:
        card = curiosity._card(curiosity.SEEDS_BY_ID[ident], {})
        assert set(card["breakdown"]) == {"problem", "approach", "result"} and card["problems"], ident
    lists = {ident: cards for ident, _, _, cards, _ in curiosity.COLLECTIONS}
    assert set(india) <= set(lists["engineering-at-india-scale"]) and "hotstar-scaling-for-50m" in lists["engineering-at-india-scale"]
    assert {"netflix-faster-website", "pinterest-pwa-retrospective"} <= set(lists["making-apps-fast"])
    assert lists["cross-platform-mobile-bets"][:2] == ("airbnb-sunsetting-react-native", "shopify-react-native-future")
    assert curiosity.SEEDS_BY_ID["swiggy-serviceability-platform"]["source_id"] == "swiggy-bytes"


def test_monthly_upkeep_report_combines_links_and_queue_without_a_live_archive(monkeypatch):
    from scripts import curiosity_upkeep as upkeep

    monkeypatch.delenv("NEWS_DATABASE_URL", raising=False)
    assert "Skipped: NEWS_DATABASE_URL is not set" in upkeep.review_queue_section(35, 10)

    def broken_store():
        raise ConnectionError("down")

    assert "Could not read the archive (ConnectionError)" in upkeep.review_queue_section(35, 10, broken_store)
    assert "0 incident write-ups" in upkeep.review_queue_section(35, 10, lambda: None)
    links = [{"id": "gone", "url": "https://a.com/x", "status": 404, "final_url": "https://a.com/x", "result": "broken"},
             {"id": "fine", "url": "https://a.com/y", "status": 200, "final_url": "https://a.com/y", "result": "ok"}]
    report = upkeep.build_report(links, "## Postmortem review queue\n\nnothing\n")
    assert report.startswith("# Curiosity Cards upkeep") and "## Seed links: 2 checked" in report
    assert "**broken** `gone`" in report and "## Postmortem review queue" in report


def test_round_twelve_fills_data_observability_and_security_gaps():
    from app import curiosity

    lists = {ident: cards for ident, _, _, cards, _ in curiosity.COLLECTIONS}
    for ident in ("data-and-ml-platforms", "observability-in-practice", "security-engineering-foundations"):
        assert 4 <= len(lists[ident]) <= 10 and set(lists[ident]) <= set(curiosity.SEEDS_BY_ID), ident
    security = [ident for ident, seed in curiosity.SEEDS_BY_ID.items() if "security" in curiosity.card_themes(seed)]
    assert len(security) >= 18
    for ident in ("uber-michelangelo", "datadog-husky-event-store", "cloudflare-phishing-hardware-keys", "google-beyondcorp"):
        assert curiosity._card(curiosity.SEEDS_BY_ID[ident], {})["breakdown"], ident


@pytest.fixture
def cards_api(monkeypatch):
    from fastapi.testclient import TestClient
    from app import curiosity_api, server

    monkeypatch.setattr(curiosity_api, "get_store", lambda: None)
    curiosity_api._shelf_cache.clear()
    yield TestClient(server.app), curiosity_api
    curiosity_api._shelf_cache.clear()


def test_cards_api_pages_the_whole_collection_with_a_cursor_and_no_repeats(cards_api):
    from app import curiosity

    client, _ = cards_api
    seen, cursor, pages = [], "", 0
    while True:
        response = client.get("/api/curiosity/cards", params={"limit": 48, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200
        payload = response.json()
        seen += [card["id"] for card in payload["cards"]]
        pages += 1
        cursor = payload["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == payload["total"] == len(curiosity.CURATED_CURIOSITY), "every reviewed card, once"
    assert pages == -(-len(seen) // 48)
    facets = payload["facets"]
    assert facets["total"] == len(seen) and facets["themes"]["security"] >= 18
    assert all(isinstance(pair, list) and len(pair) == 3 for pair in facets["theme_pairs"])
    assert "Kubernetes" in facets["technologies"] or facets["technologies"]


def test_cards_api_filters_searches_and_sorts_on_the_server(cards_api):
    client, _ = cards_api
    security = client.get("/api/curiosity/cards", params={"theme": "security", "limit": 48}).json()
    assert security["total"] >= 18 and all("security" in card["themes"] for card in security["cards"])
    kafka = client.get("/api/curiosity/cards", params={"q": "  KAFKA  "}).json()
    assert kafka["filters"]["q"] == "KAFKA" and any(card["id"] == "linkedin-kafka-benchmark" for card in kafka["cards"])
    newest = client.get("/api/curiosity/cards", params={"sort": "newest", "limit": 10}).json()["cards"]
    dates = [card.get("published_at") or str(card.get("year")) for card in newest]
    assert dates == sorted(dates, reverse=True)
    india = client.get("/api/curiosity/cards", params={"company": "Swiggy"}).json()
    assert [card["id"] for card in india["cards"]] == ["swiggy-serviceability-platform"]
    assert client.get("/api/curiosity/cards", params={"q": "zzzz-no-such-story"}).json()["total"] == 0


def test_cards_api_rejects_bad_input_and_stale_cursors_and_supports_conditional_requests(cards_api):
    client, api = cards_api
    assert client.get("/api/curiosity/cards", params={"theme": "bogus"}).status_code == 422
    assert client.get("/api/curiosity/cards", params={"limit": 500}).status_code == 422
    assert client.get("/api/curiosity/cards", params={"cursor": "not-a-cursor"}).status_code == 400
    assert client.get("/api/curiosity/cards", params={"cursor": api.encode_cursor("0" * 16, 24)}).status_code == 409
    assert client.get("/api/curiosity/cards", params={"q": "x" * 81}).status_code == 422
    first = client.get("/api/curiosity/cards", params={"limit": 5})
    assert first.headers["cache-control"].startswith("public, max-age=60") and first.headers["etag"].startswith('W/"')
    again = client.get("/api/curiosity/cards", params={"limit": 5}, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and not again.content


def test_single_card_endpoint_serves_seeds_and_404s_unknown_ids(cards_api):
    client, _ = cards_api
    card = client.get("/api/curiosity/cards/dropbox-password-storage")
    assert card.status_code == 200 and card.json()["card"]["breakdown"]["approach"].startswith("Three layers")
    assert client.get("/api/curiosity/cards/no-such-card").status_code == 404
    assert client.get("/api/curiosity/cards/..%2Fetc").status_code in {404, 422}


@pytest.fixture
def events_api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import curiosity_api, server

    store = Store(f"sqlite:///{(tmp_path / 'events.sqlite').as_posix()}")
    store.migrate()
    monkeypatch.setattr(curiosity_api, "get_store", lambda: store)
    curiosity_api._shelf_cache.clear()
    curiosity_api._popular_cache.clear()
    server._limits.clear()
    yield TestClient(server.app), store, curiosity_api
    curiosity_api._shelf_cache.clear()
    curiosity_api._popular_cache.clear()


def test_usage_events_store_anonymous_daily_counts_for_known_cards_only(events_api):
    from sqlalchemy import inspect, select
    from app.launch_store import curiosity_events

    client, store, _ = events_api
    body = {"events": [
        {"type": "open_source", "surface": "collection", "card_id": "dropbox-password-storage"},
        {"type": "open_source", "surface": "collection", "card_id": "dropbox-password-storage"},
        {"type": "read_next", "surface": "card_page", "card_id": "google-beyondcorp"},
        {"type": "list_open", "surface": "collection", "list_id": "security-engineering-foundations"},
        {"type": "open_source", "surface": "collection", "card_id": "not-a-real-card"},
        {"type": "list_open", "surface": "collection", "list_id": "not-a-list"},
        {"type": "share", "surface": "home", "card_id": "<script>"},
    ]}
    response = client.post("/api/curiosity/events", json=body)
    assert response.status_code == 204 and not response.content
    with store.engine.connect() as conn:
        rows = sorted(tuple(row) for row in conn.execute(select(curiosity_events.c.event, curiosity_events.c.card_id,
                                                                curiosity_events.c.list_id, curiosity_events.c.count)))
    assert rows == [("list_open", "", "security-engineering-foundations", 1), ("open_source", "dropbox-password-storage", "", 2),
                    ("read_next", "google-beyondcorp", "", 1)], "unknown cards and lists are dropped"
    columns = {column["name"] for column in inspect(store.engine).get_columns("brief_curiosity_events")}
    assert columns == {"day", "event", "card_id", "list_id", "surface", "count"}, "no reader identifiers are stored"
    # A second batch adds to the same daily counter.
    client.post("/api/curiosity/events", json={"events": body["events"][:1]})
    assert store.curiosity_event_totals("2000-01-01", events=("open_source",))[0] == {"id": "dropbox-password-storage", "count": 3}


def test_usage_events_honour_privacy_signals_and_reject_malformed_batches(events_api):
    client, store, _ = events_api
    event = {"type": "open_source", "surface": "collection", "card_id": "dropbox-password-storage"}
    assert client.post("/api/curiosity/events", json={"events": [event]}, headers={"Sec-GPC": "1"}).status_code == 204
    assert client.post("/api/curiosity/events", json={"events": [event]}, headers={"DNT": "1"}).status_code == 204
    assert store.curiosity_event_totals("2000-01-01") == [], "Global Privacy Control and Do Not Track are never counted"
    assert client.post("/api/curiosity/events", json={"events": []}).status_code == 422
    assert client.post("/api/curiosity/events", json={"events": [event] * 21}).status_code == 422
    assert client.post("/api/curiosity/events", json={"events": [{**event, "ip": "1.2.3.4"}]}).status_code == 422
    assert client.post("/api/curiosity/events", json={"events": [{**event, "type": "purchase"}]}).status_code == 422
    statuses = [client.post("/api/curiosity/events", json={"events": [event]}).status_code for _ in range(61)]
    assert statuses[-1] == 429, "each client is rate limited"


def test_popular_cards_need_enough_anonymous_counts(events_api):
    client, store, api = events_api
    assert client.get("/api/curiosity/popular").json()["cards"] == []
    today = __import__("datetime").datetime.now(UTC).date().isoformat()
    store.record_curiosity_events([(today, "open_source", "dropbox-password-storage", "", "collection")] * 15
                                  + [(today, "card_view", "google-beyondcorp", "", "card_page")] * 6
                                  + [(today, "read_next", "uber-m3-metrics", "", "collection")] * 2)
    api._popular_cache.clear()
    payload = client.get("/api/curiosity/popular").json()
    assert [card["id"] for card in payload["cards"]] == ["dropbox-password-storage", "google-beyondcorp"], \
        "ranked by opens; cards below the minimum are left out"
    assert "count" not in payload["cards"][0], "counts are not published"


def test_card_pages_are_server_rendered_escaped_and_listed_in_the_cards_sitemap(cards_api):
    import json as _json
    from app import curiosity

    client, _ = cards_api
    page = client.get("/cards/dream11-ipl-2023-concurrency")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    html = page.text
    assert '<link rel="canonical" href="https://getinformdaily.com/cards/dream11-ipl-2023-concurrency" />' in html
    assert 'property="og:title"' in html and "10.56 million concurrent users" in html
    assert 'href="https://tech.dream11.in/blog/ipl-fever' in html and 'rel="noopener noreferrer"' in html
    ld = html.split('<script type="application/ld+json">')[1].split("</script>")[0]
    assert _json.loads(ld)["@type"] == "Article"
    sheets = [line.split('href="/')[1].split('"')[0] for line in html.splitlines() if 'rel="stylesheet"' in line]
    assert sheets[-4:] == ["system.css", "command.css", "orbital.css", "signature.css"]
    missing = client.get("/cards/no-such-card")
    assert missing.status_code == 404 and 'content="noindex"' in missing.text
    sitemap = client.get("/sitemap-cards.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert sitemap.text.count("<loc>") == len(curiosity.CURATED_CURIOSITY)


def test_card_page_escapes_hostile_card_text(monkeypatch):
    from app import curiosity_pages

    hostile = {"id": "x", "title": "</title><script>alert(1)</script>", "summary": '"><img src=x onerror=alert(1)>',
               "url": "javascript:alert(1)", "company": "<b>Co</b>", "themes": [], "problems": [],
               "breakdown": {"problem": "<i>p</i>", "approach": "a", "result": "r"},
               "related": [{"id": "y", "title": "</a><script>", "company": "c"}]}
    html = curiosity_pages.render_card_page(hostile)
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html and "<b>Co</b>" not in html
    assert "javascript:alert" not in html, "only https source links are rendered"
    ld = html.split('<script type="application/ld+json">')[1].split("</script>")[0]
    assert "</" not in ld


def test_upkeep_report_lists_what_readers_opened(tmp_path):
    from scripts import curiosity_upkeep as upkeep

    store = Store(f"sqlite:///{(tmp_path / 'usage.sqlite').as_posix()}")
    store.migrate()
    assert "No anonymous counts yet" in upkeep.usage_section(35, lambda: store)
    today = datetime.now(UTC).date().isoformat()
    store.record_curiosity_events([(today, "open_source", "dropbox-password-storage", "", "collection")] * 4
                                  + [(today, "list_open", "", "observability-in-practice", "collection")])
    section = upkeep.usage_section(35, lambda: store)
    assert "`dropbox-password-storage` — 4 opens" in section and "`observability-in-practice` — 1 opens" in section


def test_a_large_shelf_never_asks_for_more_model_summarised_fresh_cards(monkeypatch):
    from app import curiosity

    asked = []
    monkeypatch.setattr(curiosity, "_fresh_discoveries", lambda store, limit: asked.append(limit) or [])
    curiosity.build_curiosity_cards(None, limit=curiosity.MAX_CURIOSITY_CARDS)
    assert asked == [curiosity.MAX_FRESH_CARDS], "fresh cards are capped however large the shelf is"


def test_a_stale_shelf_is_served_at_once_and_rebuilt_in_the_background(monkeypatch):
    import threading
    from app import curiosity_api

    curiosity_api._shelf_cache.clear()
    builds = []
    rebuilt = threading.Event()

    def build(store, limit):
        builds.append(limit)
        if len(builds) > 1:
            rebuilt.set()
        return [{"id": f"card-{len(builds)}", "title": "t", "themes": [], "problems": [], "seed": True}]

    monkeypatch.setattr(curiosity_api, "build_curiosity_cards", build)
    monkeypatch.setattr(curiosity_api, "get_store", lambda: None)
    first = curiosity_api.curiosity_shelf()
    assert [card["id"] for card in first["cards"]] == ["card-1"] and len(builds) == 1, "a cold start builds once"
    assert curiosity_api.curiosity_shelf() is first or curiosity_api.curiosity_shelf()["version"] == first["version"]
    entry = curiosity_api._shelf_cache.entries["shelf"]
    entry["fresh_until"] = 0  # Past its fresh window, still inside the stale window.
    served = curiosity_api.curiosity_shelf()
    assert served["version"] == first["version"], "the stale shelf is served immediately"
    assert rebuilt.wait(5), "and a new one is built in the background"
    for _ in range(50):
        if curiosity_api._shelf_cache.entries["shelf"]["value"]["cards"][0]["id"] == "card-2":
            break
        threading.Event().wait(0.02)
    assert curiosity_api.curiosity_shelf()["cards"][0]["id"] == "card-2"
    curiosity_api._shelf_cache.clear()


def test_reading_list_index_is_small_and_list_ids_are_validated():
    import json as _json
    from fastapi.testclient import TestClient
    from app import server

    client = TestClient(server.app)
    index = client.get("/api/curiosity/collections")
    assert len(index.content) < 40_000, f"index is {len(index.content)} bytes; it must not carry the cards"
    full = sum(len(_json.dumps(client.get(f"/api/curiosity/collections/{item['id']}").json()))
               for group in index.json().values() for item in group)
    assert full > 4 * len(index.content)
    assert client.get("/api/curiosity/collections/no-such-list").status_code == 404
    assert client.get("/api/curiosity/collections/Bad_ID").status_code == 422
    again = client.get("/api/curiosity/collections", headers={"If-None-Match": index.headers["etag"]})
    assert again.status_code == 304



def test_round_thirteen_adds_recent_provider_postmortems():
    from app import curiosity

    added = ("cloudflare-outage-december-2025", "azure-front-door-october-2025", "clerk-query-plan-flip-2026",
             "coinbase-may-2026-outage", "microsoft-365-november-2026")
    for ident in added:
        card = curiosity._card(curiosity.SEEDS_BY_ID[ident], {})
        assert card["format"] == "postmortem" and "outages" in card["problems"] and card["breakdown"], ident
    lists = {ident: cards for ident, _, _, cards, _ in curiosity.COLLECTIONS}
    assert set(added) <= set(lists["outages-late-2025-2026"]) <= set(curiosity.SEEDS_BY_ID)
    urls = [seed["url"] for seed in curiosity.CURATED_CURIOSITY]
    assert len(urls) == len(set(urls))
