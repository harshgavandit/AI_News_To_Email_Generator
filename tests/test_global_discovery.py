from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app import server
from app.launch_store import Store, feed_validators
from app.sources import BY_ID, DEFAULT_SOURCES


def story(source_id, ident, title, *, hours=1, description="Publisher excerpt."):
    source = BY_ID[source_id]
    return {"id": ident, "source_id": source_id, "source": source.group, "publisher": source.label,
            "kind": source.kind, "category": "News", "title": title, "description": description,
            "url": f"https://{source.hosts[0]}/{ident}",
            "published_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat()}


def test_reviewed_sources_have_unique_ids():
    assert len(DEFAULT_SOURCES) == len(BY_ID)


@pytest.mark.parametrize("with_archive", [True, False])
def test_for_you_filters_and_search_select_native_language_matching_candidates(with_archive, monkeypatch, tmp_path):
    rows = [story("entarabi-ar", "matched", "جولة تمويل لتوسع الشركة الناشئة", hours=48),
            story("entarabi-ar", "other", "شركة ناشئة تطلق منصة جديدة"),
            story("entarabi", "english", "A startup announces funding"),
            story("technews-tw-chips", "chips", "台積電晶圓製造新聞")]
    store = Store(f"sqlite:///{tmp_path / 'scoped.db'}") if with_archive else None
    if store:
        for article in rows:
            store.ingest(article["source_id"], [article], True)
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": rows, "sources": []})
    server._limits.clear()
    body = {"q": "جولة تمويل", "topics": ["chips"], "scope": {"hours": 168, "region": "MENA", "language": "ar",
            "kind": "news", "coverage": "reporting", "topic": "startups", "subject": "funding"}}
    with TestClient(server.app) as client:
        response = client.post("/api/recommendations", json=body)
        assert response.status_code == 200
        assert [article["id"] for article in response.json()["articles"]] == ["matched"]
        body["scope"]["hours"] = 24
        assert client.post("/api/recommendations", json=body).json()["articles"] == []
        body["scope"]["language"] = "fake"
        assert client.post("/api/recommendations", json=body).status_code == 422


@pytest.mark.parametrize("with_archive", [True, False])
def test_facets_filter_relevance_and_counts_agree_across_storage_modes(with_archive, monkeypatch, tmp_path):
    articles = [
        story("tecnoblog", "br-title", "São Paulo: falha zero-day no Chrome", hours=3),
        story("tecnoblog", "br-excerpt", "Vazamento de dados", description="Equipes em São Paulo investigam uma falha zero day."),
        story("cert-eu", "eu-advisory", "São Paulo agencies patch zero-day vulnerabilities"),
        story("xataka-mx", "latam-software", "Software libre en São Paulo", description="El programa se llama Zero Day."),
    ]
    store = Store(f"sqlite:///{tmp_path / 'global.db'}") if with_archive else None
    monkeypatch.setattr(server, "get_store", lambda: store)
    if store:
        for article in articles:
            store.ingest(article["source_id"], [article], True)
    else:
        monkeypatch.setattr(server, "collect_news", lambda: {"articles": articles, "sources": []})
    client = TestClient(server.app)
    params = {"q": "SAO PAULO zero-day", "topic": "security", "region": "LatAm", "sort": "relevance", "limit": 1}
    response = client.get("/api/news", params=params)
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert page["facets"]["topics"]["security"] == 2
    assert page["facets"]["topics"]["software"] == 1
    assert page["facets"]["regions"]["EU"] == 1
    assert page["source_counts"]["tecnoblog"] == 2
    assert page["articles"][0]["id"] == "br-title"
    assert page["articles"][0]["region_id"] == "LatAm"
    assert "search_title" not in page["articles"][0]
    next_page = client.get("/api/news", params={**params, "cursor": page["next_cursor"]}).json()
    assert [row["id"] for row in next_page["articles"]] == ["br-excerpt"]
    assert next_page["facets"] == page["facets"]
    advisory = client.get("/api/news", params={"coverage": "advisory", "q": "sao paulo"}).json()
    assert [row["id"] for row in advisory["articles"]] == ["eu-advisory"]
    assert client.get("/api/news", params={**params, "coverage": "reporting", "cursor": page["next_cursor"]}).status_code == 400


@pytest.mark.parametrize("with_archive", [True, False])
def test_scoped_brief_filters_automatic_stories_and_keeps_outside_pin(with_archive, monkeypatch, tmp_path):
    articles = [
        story("entarabi", "mena-startup", "Egyptian startup gets a funding round"),
        story("entarabi", "mena-security", "Egyptian payments firm reports data breach"),
        story("tecnoblog", "pin", "Novo processador da Qualcomm"),
        story("betakit", "north-america-startup", "Canadian startup gets seed funding"),
    ]
    store = Store(f"sqlite:///{tmp_path / 'scoped.db'}") if with_archive else None
    monkeypatch.setattr(server, "get_store", lambda: store)
    if store:
        for article in articles:
            store.ingest(article["source_id"], [article], True)
    else:
        monkeypatch.setattr(server, "collect_news", lambda: {"articles": articles, "sources": []})
    client = TestClient(server.app)
    payload = {"edition": "world", "region": "MENA", "topic": "startups", "top_n": 3, "pinned_ids": ["pin"]}
    response = client.post("/api/digest", json=payload)
    assert response.status_code == 200, response.text
    digest = response.json()["digest"]
    assert [row["digest_id"] for row in digest["articles"]] == ["pin", "mena-startup"]
    assert "Middle East & North Africa" in digest["markdown"]
    assert digest["quick_hits"] == []
    assert client.post("/api/digest", json={**payload, "region": "invalid"}).status_code == 422
    assert client.post("/api/digest", json={**payload, "topic": "video", "pinned_ids": []}).status_code == 404


@pytest.mark.parametrize("with_archive", [True, False])
def test_native_language_search_facets_and_brief(with_archive, monkeypatch, tmp_path):
    articles = [
        story("itmedia-news", "jp-gpu", "日本の半導体メーカーが新しいＧＰＵを発表"),
        story("itmedia-news", "jp-review", "新型ＧＰＵと半導体市場", hours=2),
        story("le-monde-pixels", "fr-gpu", "Les GPU en Europe"),
        story("etnews-tech", "ko-gpu", "한국 반도체 시장과 차세대 GPU"),
    ]
    store = Store(f"sqlite:///{tmp_path / 'language.db'}") if with_archive else None
    monkeypatch.setattr(server, "get_store", lambda: store)
    if store:
        for article in articles:
            store.ingest(article["source_id"], [article], True)
    else:
        monkeypatch.setattr(server, "collect_news", lambda: {"articles": articles, "sources": []})

    with TestClient(server.app) as client:
        params = {"hours": 24, "q": "gpu", "language": "ja", "limit": 1}
        page = client.get("/api/news", params=params).json()
        assert page["total"] == 2 and page["facets"]["languages"]["fr"] == 1
        assert page["articles"][0]["topic"] == "chips"
        assert client.get("/api/news", params={**params, "language": "fr", "cursor": page["next_cursor"]}).status_code == 400
        result = client.get("/api/news", params={"q": "半導体", "language": "ja", "topic": "chips"}).json()
        assert {row["id"] for row in result["articles"]} == {"jp-gpu", "jp-review"}
        korean = client.get("/api/news", params={"q": "반도체", "language": "ko", "topic": "chips"}).json()
        assert [row["id"] for row in korean["articles"]] == ["ko-gpu"]
        response = client.post("/api/digest", json={"edition": "world", "language": "ja", "topic": "chips"})
        assert response.status_code == 200
        digest = response.json()["digest"]
        assert {row["language"] for row in digest["articles"]} == {"ja"}
        assert "Japanese" in digest["markdown"] and "半導体" in digest["html"]


@pytest.mark.parametrize("with_archive", [True, False])
def test_article_source_filters_search_and_brief(with_archive, monkeypatch, tmp_path):
    articles = [
        story("medium-codex", "medium-article", "A practical guide to message queues"),
        story("dev-architecture", "dev-article", "How to monitor message queues"),
        story("the-register", "report", "Message queues are down in London"),
    ]
    store = Store(f"sqlite:///{tmp_path / 'articles.db'}") if with_archive else None
    monkeypatch.setattr(server, "get_store", lambda: store)
    if store:
        for article in articles:
            store.ingest(article["source_id"], [article], True)
    else:
        monkeypatch.setattr(server, "collect_news", lambda: {"articles": articles, "sources": []})

    with TestClient(server.app) as client:
        view = client.get("/api/news", params={"q": "message queues", "source": "medium", "coverage": "article"}).json()
        assert [article["id"] for article in view["articles"]] == ["medium-article"]
        assert view["source_counts"]["dev"] == 1
        response = client.post("/api/digest", json={"edition": "world", "coverage": "article", "top_n": 3,
                                                    "sources": ["medium", "dev"]})
        assert response.status_code == 200
        digest = response.json()["digest"]
        assert {article["digest_id"] for article in digest["articles"]} == {"medium-article", "dev-article"}
        assert "Article or tutorial" in digest["html"]


@pytest.fixture(params=["sqlite", "postgresql"])
def legacy_archive(request, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    if request.param == "sqlite":
        yield db_url
        return
    pg_url = os.getenv("TEST_NEWS_POSTGRES_URL")
    if not pg_url:
        pytest.skip("Set TEST_NEWS_POSTGRES_URL to a disposable PostgreSQL service")
    schema_name = f"test_discovery_{uuid4().hex}"
    admin = create_engine(pg_url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f"CREATE SCHEMA {schema_name}")
    try:
        yield make_url(pg_url).update_query_dict({"options": f"-csearch_path={schema_name}"}).render_as_string(hide_password=False)
    finally:
        with admin.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA {schema_name} CASCADE")
        admin.dispose()


def test_archive_upgrade_backfills_legacy_rows_and_keeps_canonical_owner(legacy_archive):
    engine = create_engine(legacy_archive)
    article = story("anthropic-news", "legacy", "A security patch for São Paulo")
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE TABLE brief_articles (
            id VARCHAR(40) PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
            source VARCHAR(64) NOT NULL, source_id VARCHAR(64) NOT NULL, publisher VARCHAR(140) NOT NULL,
            kind VARCHAR(24) NOT NULL, category VARCHAR(100) NOT NULL, published_at VARCHAR(40) NOT NULL)""")
        conn.execute(text("""INSERT INTO brief_articles VALUES
            (:id, :url, :title, :description, :source, :source_id, :publisher, :kind, :category, :published_at)"""), article)

    def upgrade(_):
        store = Store(legacy_archive)
        store.ensure_discovery_schema()
        store.engine.dispose()

    if engine.dialect.name == "postgresql":
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(upgrade, range(2)))
    store = Store(legacy_archive)
    search_index = store.migrate()
    indexes = {index["name"] for index in inspect(engine).get_indexes("brief_articles")}
    assert "brief_articles_topic_page" in indexes
    if engine.dialect.name == "postgresql":
        assert search_index == "trigram" and "brief_articles_search_trgm" in indexes
    store.ingest("anthropic-research", [dict(article, publisher="Anthropic Research")], True,
                 diagnostics={"observed": 2, "rejected": 1})
    assert store.feed_diagnostics()["anthropic-research"]["observed"] == 2
    assert store.article_feed_ids("legacy") == {"anthropic-news", "anthropic-research"}
    page = store.page(hours=24, source="all", query="sao paulo", kind="all", publisher="", limit=12, cursor=None)
    assert [(row["id"], row["source_id"], row["topic"]) for row in page["articles"]] == [
        ("legacy", "anthropic-news", "security")]
    store.enable("anthropic-news", False)
    assert store.article_feed_ids("legacy") == {"anthropic-research"}
    store.ingest("anthropic-research", [dict(article, publisher="Anthropic Research")], True)
    assert store.pinned_articles(["legacy"])[0]["source_id"] == "anthropic-research"
    store.engine.dispose()
    engine.dispose()


def test_conditional_feed_state_is_additive_and_preserves_archive_rows(legacy_archive):
    store = Store(legacy_archive)
    store.migrate()
    feed_validators.drop(store.engine)
    assert store.current_feed_validators() == {}
    source = BY_ID["entarabi-ar"]
    story_row = story(source.id, "local-startup", "شركة ناشئة تحصل على تمويل")
    validators = {"resource_url": source.url, "etag": '"v1"', "last_modified": None}
    store.ingest(source.id, [story_row], True, feed_url=source.url, validators=validators)
    store.ingest(source.id, [], True, feed_url=source.url, unchanged=True)
    metadata = store.current_feed_validators()[source.id]
    assert metadata["etag"] == '"v1"'
    assert store.source_state()[source.id]["count"] == 1
    assert store.article(story_row["id"])["title"] == story_row["title"]
    store.engine.dispose()


def test_archive_discovery_ranks_followed_author_before_feed_sampling(legacy_archive, monkeypatch):
    from app.article_metadata import author_identity

    store = Store(legacy_archive)
    store.migrate()
    monkeypatch.setattr(server, "get_store", lambda: store)
    now = datetime.now(UTC)
    records = [story("techcrunch", f"recent-{i}", f"Startup funding report {i}") for i in range(12)]
    older = dict(story("techcrunch", "followed-author", "Startup funding in Nairobi"),
                 published_at=(now - timedelta(days=42)).isoformat(), author="Njeri Wafula")
    store.ingest("techcrunch", [*records, older], True)
    with TestClient(server.app) as client:
        result = client.post("/api/recommendations", json={"scope": {"hours": 2160, "publisher": "techcrunch"},
                             "authors": [author_identity(older)], "q": "startup funding", "limit": 3})
        assert result.status_code == 200, result.text
        first = result.json()["articles"][0]
        assert first["id"] == older["id"]
        assert "From an author you follow" in first["recommendation_reasons"]
        details = client.get("/api/articles/followed-author").json()
        assert details["summary"]["basis"] == "publisher_excerpt" and details["summary"]["limited_source"]
    store.engine.dispose()


def test_archive_relevance_upgrade_hides_non_technical_community_posts(legacy_archive):
    store = Store(legacy_archive)
    store.migrate()
    posts = [story("dev-community", "technical", "A Python guide to logging"),
             story("dev-latest", "local-ad", "Emergency towing and battery jump starts",
                   description="Our local towing service is available every day.")]
    for post in posts:
        store.ingest(post["source_id"], [post], True)
    with store.engine.begin() as conn:
        conn.execute(text("ALTER TABLE brief_articles DROP COLUMN community_relevant"))
    store._discovery_ready = False
    store.ensure_discovery_schema()
    page = store.page(hours=24, source="dev", query="", kind="all", publisher="", limit=10, cursor=None)
    assert page["total"] == 1
    assert [item["id"] for item in page["articles"]] == ["technical"]
    assert store.article("local-ad") is None
    with store.engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM brief_articles")) == 2
    store.engine.dispose()


def test_source_scope_upgrade_hides_old_out_of_section_stories(legacy_archive):
    store = Store(legacy_archive)
    store.migrate()
    rows = [dict(story("scmp-tech", "tech-story", "A cloud computing expansion"),
                 url="https://www.scmp.com/tech/tech-trends/article/123/expansion"),
            dict(story("scmp-tech", "world-story", "An unrelated public affairs story"),
                 url="https://www.scmp.com/news/world/article/124/affairs")]
    store.ingest("scmp-tech", rows, True)
    with store.engine.begin() as conn:
        conn.execute(text("ALTER TABLE brief_articles DROP COLUMN source_eligible"))
    store._discovery_ready = False
    store.ensure_discovery_schema()
    page = store.page(hours=24, source="all", query="", kind="all", publisher="", limit=10, cursor=None)
    assert [row["id"] for row in page["articles"]] == ["tech-story"]
    assert store.article("world-story") is None
    with store.engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM brief_articles")) == 2
    store.engine.dispose()
