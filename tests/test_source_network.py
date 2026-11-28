from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import time
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import update

from app import discovery_health, ingestion, scholarly, server
from app.article_metadata import extract_technical_terms
from app.discovery import relevance_score, search_terms, search_text
from app.launch_store import CLASSIFICATION_VERSION, Store, articles, feed_checks
from app.sources import BY_ID, Source, load_source_pack, validate_source
from app.trending import extract_trending
from scripts.discover_source_feeds import discover, discover_many


def item(source_id, ident="fixture", title="A technical update"):
    source = BY_ID[source_id]
    return dict(id=ident, url=f"https://{source.hosts[0]}/{ident}", title=title, description="A short source excerpt.",
        source_id=source_id, source=source.group, publisher=source.label, kind=source.kind, category="News",
        published_at=datetime.now(UTC).isoformat())


def test_pack_rejects_duplicate_ids_and_nonpublic_endpoints(tmp_path):
    row = dict(id="reviewed", group="reviewed", label="A publisher", kind="news", topic="software",
               url="https://publisher.example/feed", hosts=["publisher.example"])
    path = tmp_path / "pack.json"
    path.write_text(json.dumps([row, row]))
    with pytest.raises(ValueError):
        load_source_pack(path)
    with pytest.raises(ValueError):
        validate_source(Source(**{**row, "url": "https://127.0.0.1/private"}))
    with pytest.raises(ValueError):
        validate_source(Source(**{**row, "format": "unreviewed"}))


def test_podcast_focus_repairs_existing_archive_classification(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'podcast-classification.db'}")
    source = BY_ID["darknet-diaries"]
    assert source.topic == "security" and source.collection == "Security"
    story = item(source.id, title="Jack Rhysider interviews a guest")
    store.ingest(source.id, [story], True)
    with store.engine.begin() as conn:
        conn.execute(update(articles).where(articles.c.id == story["id"]).values(
            topic="ai", classification_version=CLASSIFICATION_VERSION - 1))
    store.migrate()
    repaired = store.article(story["id"])
    assert repaired["topic"] == "security"
    assert repaired["classification_version"] == CLASSIFICATION_VERSION
    store.migrate()
    assert store.article(story["id"])["topic"] == "security"


def test_tech_news_podcasts_are_discoverable_by_format(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'tech-podcasts.db'}")
    episode_paths = {
        "bbc-tech-life": "/programmes/tech-update",
        "bloomberg-tech-podcast": "/shows/bloomberg-tech/tech-update",
    }
    for source_id, path in episode_paths.items():
        source = BY_ID[source_id]
        assert source.enabled and source.content_format == "podcast"
        story = item(source_id, ident=source_id)
        story["url"] = f"https://{source.hosts[0]}{path}"
        store.ingest(source_id, [story], True)
    store.ingest("techcrunch", [item("techcrunch")], True)
    monkeypatch.setattr(server, "get_store", lambda: store)
    with TestClient(server.app) as client:
        response = client.get("/api/news", params={"kind": "podcast", "hours": 168})
    assert response.status_code == 200
    assert {row["source_id"] for row in response.json()["articles"]} == set(episode_paths)


def test_due_plan_is_bounded_host_aware_and_fair(monkeypatch):
    sources = tuple(Source(f"project-{i}", "projects", f"Project {i}", "engineering",
                    f"https://github.com/org/p{i}/releases.atom", ("github.com",), refresh_minutes=60) for i in range(10))
    other = replace(sources[0], id="other", url="https://publisher.example/feed", hosts=("publisher.example",))
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (*sources, other))
    now = time.time()
    first = ingestion.refresh_plan({}, maximum=8, now=now, per_host=6)
    assert len(first) == 7 and other in first
    state = {source.id: {"checked": now, "available": True} for source in first}
    pending = {source.id for source in (*sources, other)} - state.keys()
    second = ingestion.refresh_plan(state, source_ids=pending, maximum=8, now=now + 1)
    assert len(second) == 4 and not set(first) & set(second)
    state[second[0].id] = {"checked": now, "available": False, "retry_at": now + 900}
    assert second[0] not in ingestion.refresh_plan(state, source_ids=pending, maximum=8, now=now + 2)


def test_thai_feed_surfaces_by_language_and_topic_and_keeps_credit_in_the_brief(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'thai.db'}")
    story = item("blognone", title="พบช่องโหว่ใหม่ในซอฟต์แวร์", ident="node/123")
    story.update(author="example-editor")
    store.ingest("blognone", [story], True)
    monkeypatch.setattr(server, "get_store", lambda: store)
    client = TestClient(server.app)

    assert client.get("/api/sources").json()["languages"]["th"] == "Thai"
    payload = client.get("/api/news", params={"language": "th", "region": "APAC", "topic": "security"}).json()
    (article,) = payload["articles"]
    assert (article["publisher"], article["author"], article["sourceUrl"]) == (
        "Blognone", "example-editor", story["url"])
    digest = client.post("/api/digest", json={"edition": "world", "language": "th"}).json()["digest"]
    assert "Blognone · example-editor" in digest["html"]
    assert "Blognone · example-editor" in digest["markdown"]


def test_check_history_opml_and_podcast_api(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'network.db'}")
    source = BY_ID["practicalai"]
    story = item(source.id)
    store.ingest(source.id, [story], True, duration_ms=120)
    store.ingest(source.id, [], False, "rate_limited", duration_ms=80)
    history = store.source_health_history(source.id)
    assert history["checks"] == 2 and history["successful"] == 1 and history["average_duration_ms"] == 100
    monkeypatch.setattr(discovery_health, "get_store", lambda: store)
    monkeypatch.setattr(server, "get_store", lambda: store)
    client = TestClient(server.app)
    assert client.get(f"/api/discovery/sources/{source.id}/health").json()["history"]["checks"] == 2
    assert client.get("/api/discovery/sources/not-reviewed/health").status_code == 404
    opml = client.get("/api/discovery/sources.opml")
    assert opml.status_code == 200
    entries = ET.fromstring(opml.content).findall(".//outline[@xmlUrl]")
    assert any(entry.attrib["xmlUrl"] == source.url for entry in entries)
    assert all(entry.attrib["xmlUrl"].startswith("https://") for entry in entries)
    response = client.get("/api/news?hours=24&kind=podcast&limit=5")
    assert response.status_code == 200 and response.json()["articles"][0]["content_format"] == "podcast"
    with store.engine.begin() as conn:
        conn.execute(feed_checks.insert().values(source_id=source.id, checked=time.time() - 8 * 86400,
            available=False, count=0, unchanged=False))
    store.prune()
    assert store.source_health_history(source.id, 168)["checks"] == 2


def test_technical_identifiers_remain_searchable_beyond_display_excerpt(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'search.db'}")
    story = item("google-threat-intelligence", title="A new agentic security investigation")
    story["technical_terms"] = extract_technical_terms("Code reference exploit_agent and CVE-2026-12345. <script>bad()</script>")
    assert story["technical_terms"] == ["exploit_agent", "CVE-2026-12345"]
    store.ingest(story["source_id"], [story], True)
    query = search_text("exploit_agent")
    page = store.page(hours=24, source="all", query=query, kind="all", publisher="", limit=5, cursor=None)
    assert page["total"] == 1
    assert relevance_score(story, query, search_terms(query)) is not None
    assert client_subject(store, "agents")["total"] == 1


def client_subject(store, subject):
    return store.page(hours=24, source="all", query="", kind="all", publisher="", limit=5, cursor=None, subject=subject)


def test_scholarly_metadata_preserves_dates_and_never_copies_abstract(monkeypatch):
    monkeypatch.setattr(scholarly, "_last_request", 0)
    monkeypatch.setattr(scholarly, "_blocked_until", 0)
    today = datetime.now(UTC)
    record = {"type": "journal-article", "DOI": "10.1234/EXAMPLE", "title": ["Agent research"],
              "published": {"date-parts": [[today.year, today.month, today.day]]},
              "abstract": "Copyrighted abstract with exploit_agent.", "author": [{"given": "A", "family": "Researcher"}]}
    body = json.dumps({"message": {"items": [record, {**record, "DOI": "10.1234/undated", "published": {"date-parts": [[today.year]]}}]}}).encode()
    stories, status = scholarly.read_crossref(BY_ID["crossref-nature-mi"], lambda _: body)
    assert status["available"] and len(stories) == 1
    assert stories[0]["url"] == "https://doi.org/10.1234/example"
    assert stories[0]["description"] == "" and stories[0]["publication_date_precision"] == "day"
    assert "Copyrighted" not in str(stories)


@pytest.mark.parametrize("source_ids", [
    ("aws-architecture", "aws-database", "aws-developer"),
    ("project-zero", "android-developers", "google-security"),
])
def test_related_official_feeds_do_not_inflate_independent_trends(source_ids):
    rows = [item(source, str(i), f"NVIDIA platform update number {i}") for i, source in enumerate(source_ids)]
    trend = next(row for row in extract_trending(rows)["trending"] if row["tag"] == "NVIDIA")
    assert trend["source_count"] == 1


def test_feed_discovery_returns_declared_safe_links_without_activation():
    body = b'''<link rel="alternate" type="application/rss+xml" href="/feed.xml">
      <link rel="alternate" type="application/atom+xml" href="javascript:bad()">'''
    assert discover("https://publisher.example/blog", lambda _: body) == [
        {"url": "https://publisher.example/feed.xml", "type": "application/rss+xml", "discovered_from": "https://publisher.example/blog"}]


def test_bulk_discovery_isolates_failures_and_requires_public_seed_pages():
    def fetch(url):
        if "broken" in url:
            raise TimeoutError("upstream unavailable")
        return b'<link rel="alternate" type="application/atom+xml" href="/atom.xml">'

    report = discover_many(["https://publisher.example/blog", "https://broken.example/", "https://publisher.example/blog"], fetch)
    assert report["activated"] is False and len(report["results"]) == 2
    assert [row["status"] for row in report["results"]] == ["discovered", "unavailable"]
    assert report["results"][1]["error"] == "TimeoutError"
    for seeds in ([], ["http://publisher.example/"], ["https://127.0.0.1/"], "https://publisher.example/"):
        with pytest.raises(ValueError):
            discover_many(seeds, fetch)


def test_coverage_distinguishes_failed_checks_quiet_publishers_and_missing_stories(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'coverage.db'}")
    monkeypatch.setattr(discovery_health, "get_store", lambda: store)
    source = BY_ID["bbc-tech"]
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    old_story = {**item(source.id, title="Cloud infrastructure architecture"),
                 "published_at": (datetime.now(UTC) - timedelta(days=32)).isoformat()}
    store.ingest(source.id, [old_story], True)
    client = TestClient(server.app)
    report = client.get("/api/discovery/coverage").json()
    assert report["attention"]["failed_sources"] == 0
    assert report["attention"]["quiet_sources"] == 1
    assert next(topic for topic in report["topics"] if topic["id"] == "research")["gap"] == "no_sources"
    assert next(topic for topic in report["topics"] if topic["id"] == source.topic)["gap"] == "no_recent_stories"
    store.ingest(source.id, [], False, "fetch_failed")
    failed = client.get("/api/discovery/coverage").json()
    assert failed["attention"]["failed_sources"] == 1
    assert next(topic for topic in failed["topics"] if topic["id"] == source.topic)["gap"] == "checks_overdue"
    assert sum(region["sources"] for region in failed["regions"]) == 1


def test_owner_refresh_batches_require_auth_and_only_accept_reviewed_ids(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'owner.db'}")
    monkeypatch.setenv("ADMIN_TOKEN", "source-owner-test-key-0123456789abcdef0123")
    monkeypatch.setattr(server, "get_store", lambda: store)
    calls = []
    monkeypatch.setattr(server, "run_sweep", lambda **kwargs: calls.append(kwargs) or {"status": "complete"})
    client = TestClient(server.app)
    body = {"source_ids": ["practicalai"]}
    assert client.post("/api/admin/refresh", json=body).status_code == 401
    headers = {"Authorization": "Bearer source-owner-test-key-0123456789abcdef0123"}
    assert client.post("/api/admin/refresh", json={"source_ids": ["https://internal.example"]}, headers=headers).status_code == 422
    assert not calls
    assert client.post("/api/admin/refresh", json=body, headers=headers).status_code == 200
    assert calls == [{"source": None, "source_ids": {"practicalai"}, "owner": True}]


def test_freshness_follows_the_last_sweep_after_its_grace_period():
    morning = datetime(2026, 11, 17, 2, 30, tzinfo=UTC)
    evening = morning + timedelta(hours=12)
    feed = {"available": True, "last_success": morning.isoformat()}
    assert ingestion.source_freshness(feed, evening + timedelta(minutes=44)) == "fresh"
    assert ingestion.source_freshness(feed, evening + timedelta(minutes=45)) == "stale"
