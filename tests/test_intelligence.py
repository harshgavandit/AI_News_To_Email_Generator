"""Critical discovery journeys use isolated archives and synthetic upstream transport."""
from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app import community, news, server
from app.article_metadata import metadata_for, public_link, restore_metadata
from app.coverage import public_article
from app.intelligence import deduplicate, recommend, subjects_for
from app.launch_store import Store
from app.sources import BY_ID
from app.trending import extract_trending


def story(ident, *, source_id="dev-community", title="A programming guide to Python", age=1, **extra):
    source = BY_ID[source_id]
    return {"id": ident, "title": title, "description": "An author explains the available implementation.",
            "url": f"https://{source.hosts[0]}/{ident}", "source_id": source.id, "source": source.group,
            "publisher": source.label, "kind": source.kind, "category": "Software",
            "published_at": (datetime.now(UTC) - timedelta(hours=age)).isoformat(), **extra}


@pytest.mark.parametrize("value", ["http://dev.to/a", "https://127.0.0.1/", "https://[::1]/", "https://localhost/",
                                  "https://metadata.internal/", "https://192.168.1.1/", "https://user:pass@dev.to/a",
                                  "https://dev.to:8443/a", "javascript:alert(1)", "https://dev.to/a\n"])
def test_untrusted_metadata_links_cannot_target_private_or_unsafe_urls(value):
    assert public_link(value) == ""
    assert "original_url" not in metadata_for({"original_url": value})


def test_metadata_survives_archive_without_html_bodies_or_unreviewed_images(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'metadata.db'}")
    item = story("metadata", author="<script>bad()</script><b>Ada Lovelace</b>", tags=["Python", "Cloud", "Python"],
                 thumbnail_url="https://media2.dev.to/image.png", full_text="A full copyrighted article.",
                 original_url="https://example.org/original", reading_time_minutes=7)
    store.ingest(item["source_id"], [item], True)
    result = public_article(store.article(item["id"]))
    assert result["author"] == "Ada Lovelace" and result["tags"] == ["python", "cloud"]
    assert result["thumbnail_url"] == item["thumbnail_url"] and result["readingTimeMinutes"] == 7
    assert result["reading_time_basis"] == "publisher" and result["reading_policy"] == "excerpt"
    assert {"programming", "cloud"} <= set(result["subjects"])
    assert not {"full_text", "metadata_json", "subject_keys", "search_title"} & result.keys()
    unsafe = restore_metadata({"thumbnail_url": "https://evil.example/image", "original_url": "javascript:bad()"})
    assert "thumbnail_url" not in unsafe and "original_url" not in unsafe
    store.engine.dispose()


@pytest.mark.parametrize("with_archive", [True, False])
def test_reader_compares_recent_coverage_without_merging_individual_articles(monkeypatch, tmp_path, with_archive):
    headline = "Northstar recalls 200 Falcon battery packs after overheating reports"
    rows = [story("lead", source_id="the-verge", title=headline),
            story("match", source_id="ars-technica", title=headline + " surface"),
            story("same-publisher", source_id="the-verge", title=headline),
            story("old", source_id="bbc-tech", title=headline, age=80),
            story("different-number", source_id="bbc-tech", title=headline.replace("200", "500")),
            story("post", source_id="dev-community", title=headline + " in a Python simulator"),
            story("other", source_id="wired", title="Northstar ships a smaller Falcon battery pack")]
    store = Store(f"sqlite:///{tmp_path / 'compare.db'}") if with_archive else None
    if store:
        for item in rows:
            store.ingest(item["source_id"], [item], True)
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": rows, "sources": []})
    client = TestClient(server.app)
    response = client.get("/api/articles/lead")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    matches = response.json()["coverage"]
    assert [item["id"] for item in matches] == ["match"]
    assert matches[0]["related_reason"] == "Closely matching headlines"
    assert matches[0]["url"] == rows[1]["url"]
    reverse = client.get("/api/articles/match").json()["coverage"]
    assert [item["source_id"] for item in reverse] == ["the-verge"]
    if store:
        store.enable("ars-technica", False)
        assert client.get("/api/articles/lead").json()["coverage"] == []
        store.engine.dispose()


def test_common_headline_words_do_not_create_related_coverage(monkeypatch):
    rows = [story("robotaxi", source_id="techcrunch", title="Zoox robotaxis are now on the Uber app in Las Vegas"),
            story("unrelated", source_id="dev-community", title="Muse Spark models are now live on Google Cloud")]
    monkeypatch.setattr(server, "get_store", lambda: None)
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": rows, "sources": []})
    assert TestClient(server.app).get("/api/articles/robotaxi").json()["related"] == []


def test_official_dev_api_validates_fields_and_deduplicates_with_rss(monkeypatch):
    payload = [{"title": "Learn Rust", "url": "https://dev.to/author/rust", "published_at": datetime.now(UTC).isoformat(),
                "description": "Memory safety and ownership.", "user": {"name": "A Developer"},
                "canonical_url": "https://author.example/rust", "tag_list": ["rust", "opensource"],
                "comments_count": 4, "public_reactions_count": 12, "reading_time_minutes": 5},
               {"title": "Unsafe URL", "url": "https://dev.to.evil.example/x"},
               {"title": "Malformed date", "url": "https://dev.to/user/x", "published_at": "invalid"},
               {"title": "Emergency towing and battery jump starts", "url": "https://dev.to/user/local-ad",
                "published_at": datetime.now(UTC).isoformat(), "tag_list": ["local", "services"]}]
    monkeypatch.setattr(news, "fetch_bytes", lambda _: json.dumps(payload).encode())
    rows, status = news.read_feed(BY_ID["dev-community"])
    assert status["available"] and len(rows) == 1
    article = rows[0]
    assert article["author"] == "A Developer" and article["comments_count"] == 4
    assert article["id"] == community.record(BY_ID["dev-community"], "Learn Rust", article["url"],
                                             article["published_at"])["id"]
    assert status["integration"] == "dev-api"


@pytest.mark.parametrize("payload", [b"<html>rate limit</html>", b'{"error":"rate limited"}', b"null"])
def test_invalid_official_api_responses_report_failure(monkeypatch, payload):
    monkeypatch.setattr(news, "fetch_bytes", lambda _: payload)
    rows, status = news.read_feed(BY_ID["dev-community"])
    assert not rows and not status["available"] and status["error"] == "api_unavailable"


def test_hn_official_api_partial_failures_keep_attribution_and_never_fetch_linked_articles(monkeypatch):
    requested = []
    def transport(request):
        requested.append(str(request.url))
        path = request.url.path
        if path.endswith("topstories.json"):
            return httpx.Response(200, json=[1, 2, 3, "malicious"])
        if path.endswith("newstories.json"):
            return httpx.Response(503)
        if path.endswith("showstories.json"):
            return httpx.Response(200, json=[1])
        if path.endswith("item/1.json"):
            return httpx.Response(200, json={"id": 1, "type": "story", "time": int(datetime.now(UTC).timestamp()),
                "title": "Show HN: A new compiler", "url": "https://compiler.example/project", "by": "engineer",
                "score": 30, "descendants": 6, "text": "Never present submitter text as publisher coverage."})
        if path.endswith("item/2.json"):
            return httpx.Response(200, json={"id": 2, "deleted": True})
        return httpx.Response(503)
    original = httpx.AsyncClient
    monkeypatch.setattr(community.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    rows, status = news.read_feed(BY_ID["hacker-news"])
    assert status["available"] and len(rows) == 1
    article = rows[0]
    assert article["original_url"] == "https://compiler.example/project"
    assert article["url"] == article["discussion_url"] == "https://news.ycombinator.com/item?id=1"
    assert article["description"] == "" and article["points"] == 30
    assert all(url.startswith(community.HN_BASE) for url in requested)


def test_hn_total_deadline_preserves_completed_stories(monkeypatch):
    import asyncio
    real_timeout = asyncio.timeout
    monkeypatch.setattr(community.asyncio, "timeout", lambda _: real_timeout(.05))
    async def transport(request):
        if "/item/" not in request.url.path:
            return httpx.Response(200, json=[1, 2])
        if request.url.path.endswith("/2.json"):
            await asyncio.sleep(1)
        return httpx.Response(200, json={"id": 1, "type": "story", "title": "A compiler release",
            "time": int(datetime.now(UTC).timestamp()), "url": "https://compiler.example/release"})
    original = httpx.AsyncClient
    monkeypatch.setattr(community.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    rows, status = news.read_feed(BY_ID["hacker-news"])
    assert status["available"] and len(rows) == 1 and rows[0]["title"] == "A compiler release"


@pytest.fixture(params=[True, False], ids=["archive", "direct"])
def discovery_client(request, monkeypatch, tmp_path):
    rows = [story("python", author="Ada Lovelace", tags=["programming", "python"]),
            story("cloud", title="Kubernetes adds cloud observability", tags=["cloud"], author="Grace Hopper"),
            story("research", source_id="arxiv-programming", title="An empirical study of compiler correctness"),
            story("acquisition", source_id="techcrunch", title="A startup acquires a database company"),
            story("advisory", source_id="kubernetes-advisories", title="CVE-2026-12345: Restricted workloads"),
            story("cross-report", source_id="the-hacker-news", title="Privilege escalation fixed in a container runtime",
                  age=200, description="The publisher identifies this issue as CVE-2026-12345."),
            story("release", source_id="uv-releases", title="uv 0.13.8")]
    store = Store(f"sqlite:///{tmp_path / 'journey.db'}") if request.param else None
    if store:
        for item in rows:
            store.ingest(item["source_id"], [item], True)
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(server, "collect_news", lambda: {"articles": rows, "sources": []})
    monkeypatch.setattr(server, "queue_archive_refresh", lambda _jobs, _store, _filters, _key, page, **_: page)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    server._news_cache.clear()
    server._limits.clear()
    with TestClient(server.app) as client:
        yield client
    if store:
        store.engine.dispose()


def test_author_search_subject_filters_and_cursor_are_consistent(discovery_client):
    client = discovery_client
    result = client.get("/api/news", params={"q": "Ada Lovelace", "subject": "programming"})
    assert result.status_code == 200
    assert [item["id"] for item in result.json()["articles"]] == ["python"]
    assert client.get("/api/news?subject=cloud").json()["total"] == 1
    assert client.get("/api/news?subject=acquisitions").json()["total"] == 1
    page = client.get("/api/news?subject=programming&limit=1").json()
    assert page["next_cursor"]
    assert client.get("/api/news", params={"cursor": page["next_cursor"], "subject": "cloud", "limit": 1}).status_code == 400
    assert client.get("/api/news?subject=unsupported").status_code == 422


def test_recommendations_and_related_reading_journey(discovery_client):
    client = discovery_client
    response = client.post("/api/recommendations", json={"subjects": ["cloud"], "sources": ["dev"]})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["personalized"] and data["articles"][0]["id"] == "cloud"
    assert "Matches Cloud & infrastructure" in data["articles"][0]["recommendation_reasons"]
    detail = client.get("/api/articles/cloud")
    assert detail.status_code == 200 and detail.json()["article"]["author"] == "Grace Hopper"
    assert detail.json()["summary"]["limited_source"]
    assert all(row["id"] != "cloud" for row in detail.json()["related"])
    assert client.get("/api/articles/not-found").status_code == 404
    assert client.post("/api/recommendations", json={"sources": ["unreviewed"]}).status_code == 422
    assert client.post("/api/recommendations", json={"subjects": ["arbitrary"]}).status_code == 422
    assert client.post("/api/recommendations", json={"url": "https://localhost"}).status_code == 422


def test_subject_filtered_brief_preserves_selection(discovery_client):
    response = discovery_client.post("/api/digest", json={"edition": "world", "subject": "cloud", "top_n": 3})
    assert response.status_code == 200
    digest = response.json()["digest"]
    assert [article["digest_id"] for article in digest["articles"]] == ["cloud"]
    assert "Cloud &amp; infrastructure" in digest["html"]
    assert discovery_client.post("/api/digest", json={"edition": "world", "subject": "arbitrary"}).status_code == 422


def test_release_filter_and_related_reference_journey(discovery_client):
    page = discovery_client.get("/api/news?coverage=release").json()
    assert [item["id"] for item in page["articles"]] == ["release"]
    assert page["coverage_types"]["release"] == "Release notes"
    preview = discovery_client.post("/api/digest", json={"edition": "world", "coverage": "release", "top_n": 3})
    assert preview.status_code == 200
    assert "Official release notes" in preview.json()["digest"]["html"]
    detail = discovery_client.get("/api/articles/advisory").json()
    assert [item["id"] for item in detail["related"]] == ["cross-report"]
    assert "CVE-2026-12345" in detail["related"][0]["related_reason"]


def test_recommendation_freshness_diversity_duplicates_and_exclusions():
    rows = [story(f"dev-{index}", title=f"Python programming lesson {index}") for index in range(8)]
    rows += [story("other", source_id="github-blog", title="Python programming tools"),
             story("duplicate", source_id="hacker-news", original_url=rows[0]["url"]),
             story("expired", age=31 * 24), story("future", age=-4)]
    result = recommend(rows, subjects=["programming"], exclude_ids=["dev-1"], limit=5)
    ids = [row["id"] for row in result["articles"]]
    assert not {"dev-1", "expired", "future"} & set(ids)
    assert not {"dev-0", "duplicate"} <= set(ids)
    assert "other" in ids[:3]


def test_existing_archive_upgrade_preserves_rows_and_backfills_subjects(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'upgrade.db'}")
    store.ingest("dev-community", [story("legacy", tags=["python"], author="Ada")], True)
    with store.engine.begin() as conn:
        conn.execute(text("UPDATE brief_articles SET subject_keys=NULL"))
    store._discovery_ready = False
    store.migrate()
    assert "metadata_json" in {column["name"] for column in inspect(store.engine).get_columns("brief_articles")}
    assert store.page(hours=24, source="all", query="ada", kind="all", publisher="", limit=5, cursor=None,
                      subject="programming")["total"] == 1
    store.engine.dispose()


def test_trending_is_source_based_searchable_and_excludes_future_records():
    rows = [story("funding", title="Startup closes a seed round"), story("future", title="OpenAI news", age=-2)]
    result = extract_trending(rows)
    assert result["total_analyzed"] == 1
    trend = next(row for row in result["trending"] if row["category"] == "startups")
    assert trend["query"] == "seed round" and trend["count"] == 1


def test_cross_publisher_advisory_trend_and_preprint_deduplication():
    first = dict(story("v1"), url="https://arxiv.org/abs/2611.12345v1")
    second = dict(story("v2"), url="https://arxiv.org/pdf/2611.12345v2.pdf")
    assert deduplicate([first, second]) == [first]
    title = "Patch available for CVE-2026-12345"
    result = extract_trending([
        story("vendor", source_id="kubernetes-advisories", title=title),
        story("report", source_id="the-hacker-news", title=title),
    ])
    assert {"tag": "CVE-2026-12345", "query": "cve 2026 12345", "category": "security",
            "count": 2, "source_count": 2} in result["trending"]


def test_subject_classification_preserves_multidisciplinary_context():
    assert {"cloud", "open-source", "data"} <= set(subjects_for(story("multi", title="Open-source PostgreSQL on Kubernetes")))


@pytest.mark.parametrize("value", ["http://example.com/a", "https://127.0.0.1/a", "https://[::1]/a",
                                  "https://localhost/a", "https://service.internal/a", "https://user:pass@example.com/a",
                                  "https://example.com:8443/a", "javascript:alert(1)", "https://example.com/\nfoo"])
def test_untrusted_links_cannot_target_private_or_unsafe_destinations(value):
    assert public_link(value) == ""


def test_metadata_is_bounded_sanitized_and_survives_storage_without_bodies():
    raw = story("safe", author="<script>bad()</script><b>Ada</b>", tags=["Python"] * 30,
                original_url="https://author.example/post", thumbnail_url="https://evil.example/tracker.png",
                comments_count=-2, points=True, full_text="Unlicensed complete article")
    metadata = metadata_for(raw)
    assert metadata["author"] == "Ada" and metadata["tags"] == ["python"]
    assert "thumbnail_url" not in metadata and "comments_count" not in metadata and "points" not in metadata
    restored = restore_metadata({**raw, "metadata_json": json.dumps(metadata)})
    assert "full_text" not in restored and "thumbnail_url" not in restored
    public = public_article(restored)
    assert public["reading_policy"] == "excerpt" and public["reading_time_basis"] == "excerpt"
    assert "metadata_json" not in public and "full_text" not in public


def test_community_api_failure_falls_back_only_to_official_rss(monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        if url == BY_ID["dev-community"].url:
            raise httpx.ConnectError("Upstream unavailable")
        return b'<rss version="2.0"><channel><title>DEV</title></channel></rss>'
    monkeypatch.setattr(news, "fetch_bytes", fetch)
    rows, status = news.read_feed(BY_ID["dev-community"])
    assert rows == [] and status["available"] and status["transport"] == "official-rss-fallback"
    assert calls == [BY_ID["dev-community"].url, "https://dev.to/feed"]


def test_dev_rss_fallback_can_defer_next_api_attempt(monkeypatch):
    def fetch(url):
        if url == BY_ID["dev-community"].url:
            raise httpx.ConnectError("Upstream unavailable")
        request = httpx.Request("GET", url)
        response = httpx.Response(429, request=request, headers={"Retry-After": "1200"})
        response.raise_for_status()

    monkeypatch.setattr(news, "fetch_bytes", fetch)
    rows, status = news.read_feed(BY_ID["dev-community"])
    assert not rows and not status["available"]
    assert status["feed_url"] == BY_ID["dev-community"].url
    assert status["error"] == "rate_limited" and status["retry_after"] == 1200
