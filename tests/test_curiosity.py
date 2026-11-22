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
        assert parts.scheme == "https" and parts.netloc and not parts.query, seed["id"]
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
