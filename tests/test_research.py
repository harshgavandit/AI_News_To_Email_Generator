"""Research evaluations use an isolated archive and deterministic provider responses."""
from datetime import UTC, datetime, timedelta
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import monitoring, research, server
from app.launch_store import Store, monitor_alerts, monitor_profiles, monitor_watches, research_vectors
from app.sources import BY_ID


def article(ident, title, description, source_id="ars-technica", *, hours=1):
    source = BY_ID[source_id]
    return {"id": ident, "title": title, "description": description, "source": source.group,
            "source_id": source_id, "publisher": source.label, "kind": source.kind,
            "category": "Cybersecurity", "url": f"https://{source.hosts[0]}/{ident}",
            "published_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat()}


@pytest.fixture
def archive(monkeypatch, research_database):
    store = Store(research_database)
    store.migrate()
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("NEWS_AI_RESEARCH", "1")
    monkeypatch.setenv("NEWS_AI_VECTORS", "0")
    lead = "Northstar recalls Falcon battery packs after overheating reports"
    for row in [
        article("lead", lead, "Northstar announced a recall of 200 battery packs after overheating reports."),
        article("second", lead + " surface", "The company confirmed that 200 packs are included.", "the-verge"),
        article("unrelated", "New compiler for wearable devices", "A toolkit compiles programs to WebAssembly.", "wired"),
        article("headline", "Avalanche scanners detect vulnerable endpoints", "", "bbc-tech"),
    ]:
        store.ingest(row["source_id"], [row], True)
    yield store, TestClient(server.app)
    store.engine.dispose()


def activate(monkeypatch, *, vectors=False):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-provider-key")
    if vectors:
        monkeypatch.setenv("NEWS_AI_VECTORS", "1")


def test_background_monitors_run_between_visits_and_keep_private_alerts(archive, monkeypatch):
    store, browser = archive
    monkeypatch.setenv("ADMIN_TOKEN", "monitor-job-owner-0123456789abcdef0123")
    monkeypatch.setattr(monitoring, "INTERVAL", 0)
    owner = {"Authorization": "Bearer monitor-job-owner-0123456789abcdef0123"}
    prefix = "/api/intelligence/inbox"
    watches = [{"id": "battery-watch", "query": "Northstar battery packs"}]
    body = {"watches": watches}
    assert browser.get(prefix).json()["active"] is False
    assert browser.post(prefix + "/enable", headers={"Origin": "https://unrelated.example"}, json=body).status_code == 403
    response = browser.post(prefix + "/enable", json=body)
    assert response.status_code == 201
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["watches"][0]["checked"] is None
    assert browser.post("/api/admin/monitoring/check").status_code == 401
    assert browser.post("/api/admin/monitoring/check", headers=owner).json()["alerts_created"] == 0

    title = "Northstar recalls Falcon battery packs after overheating reports"
    first = article("new-report", title, "Northstar published additional detail about the battery packs.", "bbc-tech", hours=0)
    store.ingest(first["source_id"], [first], True)
    assert browser.post("/api/admin/monitoring/check", headers=owner).json()["alerts_created"] == 1
    with TestClient(server.app) as other:
        assert other.get(prefix).json()["alerts"] == []
        assert other.post(prefix + "/read").status_code == 401
    state = browser.get(prefix).json()
    assert state["unread"] == 1
    alert, = state["alerts"]
    assert "new-report" in {row["id"] for row in alert["sources"]}
    assert all(row["url"].startswith("https://") for row in alert["sources"])
    assert browser.post(prefix + "/read").json()["unread"] == 0
    assert browser.post("/api/admin/monitoring/check", headers=owner).json()["alerts_created"] == 0

    second = article("corroboration", title, "Another publisher confirmed the Northstar battery packs recall.", "wired", hours=0)
    store.ingest(second["source_id"], [second], True)
    assert browser.post("/api/admin/monitoring/check", headers=owner).json()["alerts_created"] == 0
    state = browser.get(prefix).json()
    assert len(state["alerts"]) == 1 and state["alerts"][0]["id"] == alert["id"]
    assert state["unread"] == 0 and "corroboration" in {row["id"] for row in state["alerts"][0]["sources"]}
    assert browser.put(prefix + "/watches", json={"revision": 0, "watches": watches}).status_code == 200
    assert browser.put(prefix + "/watches", json={"revision": 0, "watches": []}).status_code == 409
    assert browser.delete(prefix).json()["active"] is False
    with store.engine.connect() as conn:
        assert all(conn.execute(select(table)).first() is None for table in (monitor_profiles, monitor_watches, monitor_alerts))


def test_expired_monitor_and_matching_terms_are_purged(archive):
    store, browser = archive
    prefix = "/api/intelligence/inbox"
    watch = {"id": "one", "query": "Northstar battery"}
    assert browser.post(prefix + "/enable", json={"watches": [watch, {**watch, "id": "two"}]}).status_code == 422
    assert browser.post(prefix + "/enable", json={"watches": [watch]}).status_code == 201
    with store.engine.begin() as conn:
        conn.execute(monitor_profiles.update().values(expires=0))
    assert browser.get(prefix).json()["active"] is False
    assert monitoring.run_monitoring(store)["watches_checked"] == 0
    with store.engine.connect() as conn:
        assert conn.execute(select(monitor_watches)).first() is None


def test_cookie_holder_can_delete_an_expired_monitor_before_the_worker_purges_it(archive):
    store, browser = archive
    prefix = "/api/intelligence/inbox"
    assert browser.post(prefix + "/enable", json={"watches": [
        {"id": "expired", "query": "Kubernetes security"}]}).status_code == 201
    with store.engine.begin() as conn:
        conn.execute(monitor_profiles.update().values(expires=0))
    assert browser.delete(prefix).status_code == 200
    with store.engine.connect() as conn:
        assert conn.execute(select(monitor_profiles)).first() is None
        assert conn.execute(select(monitor_watches)).first() is None


def test_research_daily_has_source_evidence_before_a_generated_edition(archive):
    _, browser = archive
    result = browser.get("/api/intelligence/daily").json()
    assert result["brief"] is None
    assert result["source_edition"]["basis"] == "publisher_evidence"
    assert result["source_edition"]["evidence"]
    assert all(row["url"].startswith("https://") for row in result["source_edition"]["evidence"])


def good_answer(prompt, _, schema, **kwargs):
    source = json.loads(prompt)["evidence"][0]
    return schema(status="answered", limitations="Only publisher excerpts were available.", claims=[
        {"text": "Northstar recalled 200 battery packs.", "kind": "fact", "source_ids": [source["id"]],
         "quotes": [source["excerpt"][:145]]},
    ]).model_dump_json()


def test_keyword_fallback_preserves_evidence_and_clusters(archive):
    _, client = archive
    response = client.post("/api/intelligence/research", json={"q": "What happened with Northstar battery packs?", "mode": "analyze"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["retrieval"] == "keyword"
    assert data["answer"]["status"] == "unavailable"
    assert {row["id"] for row in data["evidence"]} == {"lead", "second"}
    assert set(data["clusters"][0]["article_ids"]) == {"lead", "second"}
    assert all(row["url"].startswith("https://") for row in data["evidence"])


def test_headline_only_cannot_trigger_synthesis(archive, monkeypatch):
    _, client = archive
    activate(monkeypatch)
    monkeypatch.setattr(research, "generate_response", lambda *args, **kwargs: pytest.fail("No excerpts to send"))
    data = client.post("/api/intelligence/research", json={"article_id": "headline", "mode": "analyze"}).json()
    assert data["answer"]["status"] == "insufficient"
    assert data["answer"]["claims"] == []
    assert data["evidence"][0]["excerpt"] == ""


def test_citations_are_allowlisted_and_anchor_cache_is_reused(archive, monkeypatch):
    store, client = archive
    activate(monkeypatch)
    calls = []

    def generate(prompt, system, schema, **kwargs):
        calls.append(json.loads(prompt))
        assert "untrusted data" in system
        return good_answer(prompt, system, schema, **kwargs)

    monkeypatch.setattr(research, "generate_response", generate)
    body = {"article_id": "lead", "mode": "analyze"}
    first = client.post("/api/intelligence/research", json=body).json()
    second = client.post("/api/intelligence/research", json=body).json()
    assert first["answer"] == second["answer"]
    assert len(calls) == 1
    assert first["answer"]["claims"][0]["source_ids"] == ["lead"]
    assert client.post("/api/intelligence/research", json={**body, "q": "private question"}).status_code == 422
    store.enable("ars-technica", False)
    assert client.post("/api/intelligence/research", json=body).status_code == 404


@pytest.mark.parametrize("ids, statement", [
    (["fabricated"], "Northstar announced a recall."),
    (["lead"], "Northstar recalled 999 battery packs."),
    (["lead"], "Read our report at https://attacker.example."),
    ([], "Northstar announced a recall."),
])
def test_citation_guardrails_reject_untrusted_output(archive, monkeypatch, ids, statement):
    _, client = archive
    activate(monkeypatch)
    monkeypatch.setattr(research, "generate_response", lambda *args, **kwargs: json.dumps({
        "status": "answered", "limitations": "Only excerpts are available.",
        "claims": [{"text": statement, "kind": "fact", "source_ids": ids}],
    }))
    result = client.post("/api/intelligence/research", json={"article_id": "lead", "mode": "analyze"}).json()
    assert result["answer"]["status"] == "unavailable"
    assert result["answer"]["claims"] == []
    assert result["evidence"][0]["id"] == "lead"


def mock_embedding(*, semantic):
    return research.pack_vector([float(not semantic), float(semantic), *([0.0] * (research.DIMENSIONS - 2))])


def test_hybrid_fusion_prefers_the_complete_query_to_a_generic_shared_match():
    precise = article("precise", "Kubernetes security controls for containers", "How workload controls restrict cluster access.")
    partial = article("partial", "Security incident affects a computing facility", "A status page exposed credentials.", "wired")
    results = research.select_evidence([precise, partial], [partial], question="Kubernetes security")
    assert [row["id"] for row in results] == ["precise", "partial"]


def test_semantic_retrieval_filters_weak_similarity_without_keyword_overlap(archive, monkeypatch):
    store, _ = archive
    activate(monkeypatch, vectors=True)
    from math import sqrt
    strong = research.pack_vector([.75, sqrt(1 - .75 ** 2), *([0.0] * (research.DIMENSIONS - 2))])
    weak = research.pack_vector([.38, sqrt(1 - .38 ** 2), *([0.0] * (research.DIMENSIONS - 2))])
    source_rows = store.pinned_articles(["lead", "unrelated"])
    store.save_research_vectors(research.encoder(), [
        (row, strong if row["id"] == "lead" else weak) for row in source_rows])
    monkeypatch.setattr(research, "embed", lambda _: [mock_embedding(semantic=False)])
    results, state = research.vector_results(store, "battery safety", 720, {})
    assert state == "ready" and [row["id"] for row in results] == ["lead"]


def test_job_indexes_archive_hybrid_search_honors_scope_and_changes(archive, monkeypatch):
    store, client = archive
    activate(monkeypatch, vectors=True)
    monkeypatch.setenv("CRON_SECRET", "research-test-job-secret")
    monkeypatch.setattr(research, "embed", lambda texts: [
        mock_embedding(semantic="wearable" in text or "wrist" in text) for text in texts])
    monkeypatch.setattr(research, "generate_response", lambda *args, **kwargs: json.dumps({
        "status": "insufficient", "claims": [], "limitations": "This fixture only evaluates retrieval.",
    }))
    assert client.get("/api/jobs/intelligence").status_code == 401
    response = client.get("/api/jobs/intelligence", headers={"Authorization": "Bearer research-test-job-secret"}).json()
    assert response["indexed"] == 4
    with store.engine.connect() as conn:
        assert sum(len(row) for row in conn.scalars(select(research_vectors.c.embedding))) == 4 * research.VECTOR_FORMAT.size
    body = {"q": "software for wrist computers", "mode": "search"}
    data = client.post("/api/intelligence/research", json=body).json()
    assert data["retrieval"] == "hybrid"
    assert data["evidence"][0]["id"] == "unrelated"
    assert data["evidence"][0]["match"] == "semantic"
    assert client.post("/api/intelligence/research", json={**body, "scope": {"publisher": "bbc-tech"}}).json()["evidence"] == []
    row = article("unrelated", "Handheld gaming computers announced", "A report about handheld computers.", "wired")
    store.ingest("wired", [row], True)
    updated = client.post("/api/intelligence/research", json=body).json()
    assert updated["retrieval"] == "keyword"
    assert all(item["match"] == "keyword" for item in updated["evidence"])
    assert research.index_archive(store)["indexed"] == 1
    assert research.index_archive(store)["index_status"] == "current"
    store.enable("wired", False)
    assert not any(row["id"] == "unrelated" for row in client.post("/api/intelligence/research", json=body).json()["evidence"])


def openai_error(cls, status, code=None):
    import httpx
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    body = {"error": {"code": code}} if code else None
    return cls("provider said no", response=httpx.Response(status, request=request), body=body)


def test_provider_errors_are_classified_without_messages():
    import openai
    assert research.classify_provider_error(openai_error(openai.AuthenticationError, 401)) == "authentication"
    assert research.classify_provider_error(openai_error(openai.PermissionDeniedError, 403)) == "permission"
    assert research.classify_provider_error(openai_error(openai.NotFoundError, 404)) == "model_unavailable"
    assert research.classify_provider_error(openai_error(openai.RateLimitError, 429, "insufficient_quota")) == "quota"
    assert research.classify_provider_error(openai_error(openai.RateLimitError, 429, "rate_limit_exceeded")) == "rate_limited"
    assert research.classify_provider_error(openai_error(openai.InternalServerError, 500)) == "provider_error"
    assert research.classify_provider_error(ValueError("schema")) == "invalid_output"
    assert research.CONFIGURATION_ISSUES >= {"authentication", "quota"}


def test_job_reports_an_invalid_ai_key_as_action_required(archive, monkeypatch):
    import openai
    store, client = archive
    activate(monkeypatch, vectors=True)
    monkeypatch.setenv("CRON_SECRET", "research-test-job-secret")

    def rejected(*args, **kwargs):
        raise openai_error(openai.AuthenticationError, 401)

    monkeypatch.setattr(research, "embed", rejected)
    monkeypatch.setattr(research, "generate_response", rejected)
    response = client.get("/api/jobs/intelligence", headers={"Authorization": "Bearer research-test-job-secret"}).json()
    assert response["index_status"] == "provider_unavailable" and response["brief_status"] == "unavailable"
    assert response["ai_issue"] == "authentication" and response["ai_action_required"] is True
    assert "provider said no" not in json.dumps(response)
    assert research.take_provider_issue() is None


def test_job_omits_ai_issue_when_provider_is_healthy(archive, monkeypatch):
    store, client = archive
    activate(monkeypatch, vectors=True)
    monkeypatch.setenv("CRON_SECRET", "research-test-job-secret")
    monkeypatch.setattr(research, "embed", lambda texts: [mock_embedding(semantic=False) for _ in texts])
    monkeypatch.setattr(research, "generate_response", lambda *args, **kwargs: json.dumps({
        "status": "insufficient", "claims": [], "limitations": "Fixture."}))
    research._provider_issue["value"] = "unreachable"  # A stale issue from an earlier request is not reported.
    response = client.get("/api/jobs/intelligence", headers={"Authorization": "Bearer research-test-job-secret"}).json()
    assert response["status"] == "checked" and "ai_issue" not in response


def test_scheduled_brief_validates_evidence_and_respects_source_pause(archive, monkeypatch):
    store, client = archive
    activate(monkeypatch)

    def generate(prompt, _, schema, **kwargs):
        evidence = json.loads(prompt)["evidence"]
        source = next(row for row in evidence if "200" in row["excerpt"])
        return schema(status="answered", limitations="Published excerpts only.", claims=[
            {"text": "A recall affected 200 battery packs.", "kind": "fact", "source_ids": [source["id"]],
             "quotes": [source["excerpt"][:145]]},
        ]).model_dump_json()

    monkeypatch.setattr(research, "generate_response", generate)
    assert research.refresh_research_brief(store) == "answered"
    assert research.refresh_research_brief(store) == "current"
    data = client.get("/api/intelligence/daily").json()
    assert data["status"] == "available"
    assert data["brief"]["answer"]["status"] == "answered"
    cited_id = data["brief"]["answer"]["claims"][0]["source_ids"][0]
    store.enable(store.pinned_articles([cited_id])[0]["source_id"], False)
    assert client.get("/api/intelligence/daily").json()["status"] == "pending"
    assert research.refresh_research_brief(store) == "answered"
    assert client.get("/api/intelligence/daily").json()["status"] == "available"


def test_watch_requires_all_keywords_and_can_group_multiple_sources(archive):
    _, client = archive
    response = client.post("/api/intelligence/watch", json={"watches": [
        {"id": "recall", "query": "Northstar overheating"},
        {"id": "none", "query": "Northstar WebAssembly"},
    ]}).json()
    recall, none = response["watches"]
    assert recall["clusters"][0]["coverage_count"] == 2
    assert none["clusters"] == []


def test_optional_saved_story_affinity_keeps_saved_ids_out_of_recommendations(archive):
    store, client = archive
    for item in [
        article("saved-robot", "A survey of robotics control systems", "A review of robot control."),
        article("robot-news", "New robotics control system announced", "A robotics engineering breakthrough.", "the-verge"),
    ]:
        store.ingest(item["source_id"], [item], True)
    regular = client.post("/api/recommendations", json={}).json()
    assert "saved-robot" in {row["id"] for row in regular["articles"]}
    personalized = client.post("/api/recommendations", json={"saved_ids": ["saved-robot"]}).json()
    assert "saved-robot" not in {row["id"] for row in personalized["articles"]}
    recommended = next(row for row in personalized["articles"] if row["id"] == "robot-news")
    assert any("saved story" in reason for reason in recommended["recommendation_reasons"])


def test_daily_budget_keeps_archive_search_working(archive, monkeypatch):
    _, client = archive
    activate(monkeypatch)
    monkeypatch.setenv("NEWS_AI_ANSWERS_DAILY", "0")
    monkeypatch.setattr(research, "generate_response", lambda *args, **kwargs: pytest.fail("Budget must prevent model calls"))
    result = client.post("/api/intelligence/research", json={"q": "Northstar recall", "mode": "compare"}).json()
    assert result["answer"]["status"] == "budget_limited"
    assert result["evidence"]


def test_locate_quote_tolerates_typography_but_not_changed_words():
    excerpt = "The company’s new chip — built on a 3nm process — ships in “early 2027”, executives said."
    assert research.locate_quote("the company's new chip - built on a 3nm process", excerpt) == \
        "The company’s new chip — built on a 3nm process"
    assert research.locate_quote('...ships in "early 2027", executives said.', excerpt) == \
        "ships in “early 2027”, executives said"
    assert research.locate_quote("The company's new chip ships in late 2027", excerpt) is None
    assert research.locate_quote("chip", excerpt) is None


def test_one_unverifiable_quote_drops_only_that_claim():
    evidence = [{"id": "a", "title": "Chip news", "excerpt": "The firm’s chip ships in 2027 after delays.",
                 "publisher": "Example"},
                {"id": "b", "title": "Other", "excerpt": "Regulators opened a review of the export rules.",
                 "publisher": "Other"}]
    schema = research.answer_schema(evidence, quoted=True)
    answer = schema(status="answered", limitations="Excerpts only.", claims=[
        {"text": "The chip ships in 2027.", "kind": "fact", "source_ids": ["a"], "quotes": ["The firm's chip ships in 2027."]},
        {"text": "Regulators approved the rules.", "kind": "fact", "source_ids": ["b"], "quotes": ["Regulators approved the rules"]},
    ])
    result = research.validate_answer(answer, evidence)
    assert [claim["source_ids"] for claim in result["claims"]] == [["a"]]
    assert result["claims"][0]["quotes"] == ["The firm’s chip ships in 2027"]
    only_bad = schema(status="answered", limitations="Excerpts only.", claims=[answer.claims[1]])
    with pytest.raises(ValueError, match="Citation quote not found"):
        research.validate_answer(only_bad, evidence)


def index_with(store, monkeypatch, semantic_ids):
    """Index the archive with deterministic vectors: semantic_ids share one direction, the rest another."""
    monkeypatch.setattr(research, "embed", lambda texts: [mock_embedding(semantic=False) for _ in texts])
    rows = store.pinned_articles(["lead", "second", "unrelated", "headline", *semantic_ids])
    store.save_research_vectors(research.encoder(), [
        (row, mock_embedding(semantic=row["id"] in semantic_ids)) for row in rows])


def test_query_vectors_are_embedded_once_and_reused(archive, monkeypatch):
    store, _ = archive
    activate(monkeypatch, vectors=True)
    calls = []
    monkeypatch.setattr(research, "embed", lambda texts: calls.append(texts) or [mock_embedding(semantic=True)])
    first, status = research.query_vector(store, "Wearable compilers")
    again, cached = research.query_vector(store, "  wearable   COMPILERS ")
    assert first == again and (status, cached) == ("embedded", "cached") and len(calls) == 1


def test_keyword_watch_also_alerts_on_paraphrased_coverage(archive, monkeypatch):
    store, _ = archive
    activate(monkeypatch, vectors=True)
    index_with(store, monkeypatch, {"unrelated"})
    monkeypatch.setattr(research, "embed", lambda texts: [mock_embedding(semantic=True)])
    watch = monitoring.Watch(id="w", query="smartwatch software toolchains")
    update, = research.watch_matches(store, [watch])
    assert [(row["id"], row["match"]) for row in update["evidence"]] == [("unrelated", "semantic")]
    monkeypatch.setenv("NEWS_AI_VECTORS", "0")
    assert research.watch_matches(store, [watch])[0]["evidence"] == []


def test_article_details_add_semantically_similar_reading(archive, monkeypatch):
    store, client = archive
    activate(monkeypatch, vectors=True)
    index_with(store, monkeypatch, {"unrelated", "headline"})
    related = client.get("/api/articles/unrelated").json()["related"]
    assert [(row["id"], row["related_reason"]) for row in related] == [("headline", "Similar in meaning")]
    monkeypatch.setenv("NEWS_AI_VECTORS", "0")
    assert all(row.get("related_reason") != "Similar in meaning" for row in client.get("/api/articles/unrelated").json()["related"])


def test_free_questions_reuse_answers_briefly_without_persisting_them(archive, monkeypatch):
    store, client = archive
    activate(monkeypatch)
    calls = []

    def generate(prompt, _, schema, **kwargs):
        calls.append(kwargs.get("task"))
        evidence = json.loads(prompt)["evidence"]
        source = next(row for row in evidence if "200" in row["excerpt"])
        return schema(status="answered", limitations="Published excerpts only.", claims=[
            {"text": "A recall affected 200 battery packs.", "kind": "fact", "source_ids": [source["id"]],
             "quotes": [source["excerpt"][:60]]}]).model_dump_json()

    monkeypatch.setattr(research, "generate_response", generate)
    body = {"q": "Northstar battery recall", "mode": "analyze"}
    first = client.post("/api/intelligence/research", json=body).json()["answer"]
    second = client.post("/api/intelligence/research", json=body).json()["answer"]
    assert first == second and first["status"] == "answered" and calls == ["analyze"]
    with store.engine.connect() as conn:
        from app.launch_store import summaries
        assert conn.scalar(select(summaries.c.id).limit(1)) is None
