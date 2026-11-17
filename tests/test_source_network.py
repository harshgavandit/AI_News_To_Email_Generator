from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import time
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
import pytest

from app import discovery_health, ingestion, scholarly, server
from app.article_metadata import extract_technical_terms
from app.discovery import relevance_score, search_terms, search_text
from app.launch_store import Store, feed_checks
from app.sources import BY_ID, Source, load_source_pack, validate_source
from app.trending import extract_trending
from scripts.discover_source_feeds import discover


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


def test_due_plan_is_bounded_host_aware_and_fair(monkeypatch):
    sources = tuple(Source(f"project-{i}", "projects", f"Project {i}", "engineering",
                    f"https://github.com/org/p{i}/releases.atom", ("github.com",), refresh_minutes=60) for i in range(10))
    other = replace(sources[0], id="other", url="https://publisher.example/feed", hosts=("publisher.example",))
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (*sources, other))
    now = time.time()
    first = ingestion.refresh_plan({}, due_only=True, maximum=8, now=now)
    assert len(first) == 7 and other in first
    state = {source.id: {"checked": now, "available": True} for source in first}
    second = ingestion.refresh_plan(state, due_only=True, maximum=8, now=now + 1)
    assert len(second) == 4 and not set(first) & set(second)
    state[second[0].id] = {"checked": now, "available": False, "retry_at": now + 900}
    assert second[0] not in ingestion.refresh_plan(state, due_only=True, maximum=8, now=now + 2)


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
    monkeypatch.setattr(server, "refresh_from_reader", lambda *args, **kwargs: None)
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


def test_related_official_feeds_do_not_inflate_independent_trends():
    rows = [item(source, str(i), f"NVIDIA platform update number {i}") for i, source in enumerate(
            ("aws-architecture", "aws-database", "aws-developer"))]
    trend = next(row for row in extract_trending(rows)["trending"] if row["tag"] == "NVIDIA")
    assert trend["source_count"] == 1


def test_feed_discovery_returns_declared_safe_links_without_activation():
    body = b'''<link rel="alternate" type="application/rss+xml" href="/feed.xml">
      <link rel="alternate" type="application/atom+xml" href="javascript:bad()">'''
    assert discover("https://publisher.example/blog", lambda _: body) == [
        {"url": "https://publisher.example/feed.xml", "type": "application/rss+xml", "discovered_from": "https://publisher.example/blog"}]


def test_owner_refresh_batches_require_auth_and_only_accept_reviewed_ids(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'owner.db'}")
    monkeypatch.setenv("ADMIN_TOKEN", "source-owner-test-key")
    monkeypatch.setattr(server, "get_store", lambda: store)
    calls = []
    monkeypatch.setattr(server, "refresh_sources", lambda store, only=None, **kwargs: calls.append(kwargs) or [])
    client = TestClient(server.app)
    body = {"source_ids": ["practicalai"]}
    assert client.post("/api/admin/refresh", json=body).status_code == 401
    headers = {"Authorization": "Bearer source-owner-test-key"}
    assert client.post("/api/admin/refresh", json={"source_ids": ["https://internal.example"]}, headers=headers).status_code == 422
    assert not calls
    assert client.post("/api/admin/refresh", json=body, headers=headers).status_code == 200
    assert calls[0]["source_ids"] == {"practicalai"} and calls[0]["maximum"] is None


def test_quiet_source_freshness_uses_its_declared_poll_interval():
    now = datetime.now(UTC)
    cutoff = (now - timedelta(minutes=45)).isoformat()
    feed = {"available": True, "last_success": (now - timedelta(hours=2)).isoformat(), "refresh_minutes": 360}
    assert ingestion.source_freshness(feed, cutoff) == "fresh"
    assert ingestion.source_freshness({**feed, "refresh_minutes": 10}, cutoff) == "stale"
