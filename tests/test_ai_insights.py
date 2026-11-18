"""Event grouping and private radar-history regressions."""
from datetime import UTC, datetime, timedelta
import time
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app import ai_insights, event_intelligence, radar_store
from app.launch_store import Store
from app.sources import BY_ID


def story(ident, title, excerpt, source_id, *, hours=1):
    source = BY_ID[source_id]
    return {"id": ident, "title": title, "description": excerpt, "source": source.group,
        "source_id": source_id, "publisher": source.label, "kind": source.kind,
        "category": "Cybersecurity", "url": f"https://{source.hosts[0]}/{ident}",
        "published_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat()}


def test_related_reporting_forms_one_event_without_treating_repetition_as_update(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'events.sqlite'}")
    store.migrate()
    first = story("a1", "Northstar recalls Falcon battery packs after overheating reports",
                  "Northstar recalled 200 battery packs after overheating reports.", "ars-technica")
    second = story("a2", "Northstar recalls Falcon battery packs after overheating reports",
                   "The company confirmed that 200 packs are included.", "the-verge")
    store.ingest(first["source_id"], [first], True)
    store.ingest(second["source_id"], [second], True)
    now = time.time()
    event_a, changed_a = event_intelligence.observe(store, first, now=now)
    event_b, changed_b = event_intelligence.observe(store, second, now=now + 1)
    assert changed_a and changed_b
    assert event_a == event_b
    catalog = event_intelligence.catalog(store)
    assert len(catalog) == 1
    assert catalog[0]["article_count"] == 2
    assert catalog[0]["digest_version"] == "1"
    assert len(event_intelligence.timeline(store, event_a)["entries"]) == 2
    assert not event_intelligence.timeline(store, event_a, since=1)["changes"]


def test_recent_revision_includes_its_older_anchor_in_the_short_window(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'revision.sqlite'}")
    store.migrate()
    old = story("older-story", "Cloud provider reports network disruption", "Service issues reported.",
                "ars-technica", hours=48)
    store.ingest(old["source_id"], [old], True)
    event, _ = event_intelligence.observe(store, old, now=time.time() - 86400)
    revised = dict(old, description="The provider says service has been restored.")
    event_intelligence.observe(store, revised, now=time.time())
    recent = event_intelligence.catalog(store, hours=24)
    assert len(recent) == 1
    assert recent[0]["id"] == event
    assert recent[0]["digest_version"] == "2"
    assert recent[0]["articles"][0]["id"] == old["id"]
    delta = event_intelligence.timeline(store, event, since=1)
    assert delta["revision"] == "2"
    assert [item["excerpt"] for item in delta["changes"]] == [revised["description"]]
    catchup = ai_insights.catchup(store, ai_insights.RadarProfile(followed_events=[event]), {event: "1"}, hours=24)
    assert "New since your last brief" in catchup["brief"]["html"]
    assert revised["description"] == catchup["events"][0]["change_sources"][0]["excerpt"]


def test_accepted_email_history_advances_only_after_provider_acceptance(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'radar.sqlite'}")
    store.migrate()
    mailbox = "a" * 64
    event = "b" * 32
    status, provider = store.reserve_delivery("delivery-one", [("mail:test", "today", 3)],
        event_mailbox=mailbox, event_history=[{"id": event, "version": "2"}])
    assert (status, provider) == ("new", None)
    assert radar_store.histories(store, [mailbox]).get(mailbox, {}) == {}
    store.record_delivery("delivery-one", "provider-accepted")
    assert radar_store.histories(store, [mailbox])[mailbox] == {event: "2"}


def test_migration_refreshes_cached_optional_schema_readiness(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    store._event_tables_ready = False
    store._radar_tables_ready = False
    store.migrate()
    assert event_intelligence.ready(store)
    assert radar_store.ready(store)


def test_server_registers_public_insight_routes():
    from app.server import app

    paths = set(app.openapi()["paths"])
    assert "/api/intelligence/events" in paths
    assert "/api/intelligence/explain" in paths
    assert "/api/intelligence/catchup" in paths
    assert "/api/mail/radar" in paths
    assert "/api/intelligence/converse" in paths


def test_research_numeric_validation_normalizes_translated_decimal_digits():
    from app import research

    assert research.numeric_tokens("٢١٤ million") == research.numeric_tokens("214 million")


def test_public_catchup_returns_a_signed_source_linked_preview(tmp_path, monkeypatch):
    from app import insight_api, server

    store = Store(f"sqlite:///{tmp_path / 'catchup.sqlite'}")
    store.migrate()
    row = story("catchup-1", "Global cloud providers report a network disruption",
        "Several cloud providers reported a network disruption affecting API availability.", "ars-technica")
    store.ingest(row["source_id"], [row], True)
    event_intelligence.observe(store, row)
    monkeypatch.setattr(insight_api, "get_store", lambda: store)
    request = Request({"type": "http", "method": "POST", "path": "/api/intelligence/catchup",
        "headers": [(b"user-agent", b"test")], "client": ("127.0.0.1", 8080), "scheme": "http", "query_string": b""})
    body = insight_api.catch_up(insight_api.ai_insights.CatchupRequest.model_validate({
        "profile": {"role": "engineer", "interests": ["cloud"], "language": "en"},
        "seen": {}, "hours": 168,
    }), request, Response())
    assert body["status"] == "ready"
    assert body["events"][0]["articles"][0]["url"] == row["url"]
    assert body["preview"]["digest"]["edition"] == "catchup"
    assert body["preview"]["preview_id"]


def test_explanation_requires_an_exact_publisher_quote_and_supported_numbers():
    evidence = [{"id": "source-1", "title": "Cloud provider outage affects three regions",
        "excerpt": "The company reported that service was disrupted in three regions.", "publisher": "Newsroom"}]
    model = ai_insights.explanation_schema(evidence)
    valid = model.model_validate({"status": "answered", "limitations": "The excerpt does not include recovery times.",
        "claims": [{"text": "The provider reported a disruption in three regions.", "kind": "fact", "source_id": "source-1",
            "quote": "service was disrupted in three regions"}]})
    assert ai_insights.validate_explanation(valid, evidence)["claims"][0]["source_id"] == "source-1"
    invalid_quote = model.model_validate({"status": "answered", "limitations": "The excerpt does not include recovery times.",
        "claims": [{"text": "The provider recovered in 4 minutes.", "kind": "fact", "source_id": "source-1",
            "quote": "service was disrupted in three regions"}]})
    with pytest.raises(ValueError):
        ai_insights.validate_explanation(invalid_quote, evidence)


def test_exact_package_lookup_filters_withdrawn_records_and_reuses_cache(tmp_path, monkeypatch):
    import httpx
    from app import stack_intelligence

    store = Store(f"sqlite:///{tmp_path / 'stack.sqlite'}")
    calls = []

    def query(url, *, json, timeout):
        calls.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url), json={"vulns": [
            {"id": "GHSA-test-one", "summary": "An advisory", "details": "Advisory excerpt."},
            {"id": "GHSA-test-two", "withdrawn": "2024-08-01"},
        ]})

    monkeypatch.setattr(stack_intelligence.httpx, "post", query)
    package = stack_intelligence.PackageCheck(ecosystem="npm", name="@example/library", version="1.2.3")
    result = stack_intelligence.advisories(store, package)
    assert [item["id"] for item in result["evidence"]] == ["GHSA-test-one"]
    assert stack_intelligence.advisories(store, package) == result
    assert calls == [("https://api.osv.dev/v1/query", {"package": {"ecosystem": "npm", "name": "@example/library"}, "version": "1.2.3"})]
    rows = [{"title": "Compute incident in us-central1", "publisher": "Google Cloud Status", "coverage": "status"}]
    assert stack_intelligence.mentions("Google Cloud | us-central1", rows)
    assert not stack_intelligence.mentions("Google Cloud | europe-west1", rows)


def test_global_comparison_validates_distinct_publisher_evidence():
    from app import research

    evidence = [
        {"id": "one", "publisher": "First", "publisher_family": "publisher", "title": "Regional outage", "excerpt": "The operator restored service in the capital."},
        {"id": "two", "publisher": "Second", "publisher_family": "publisher", "title": "Service interruption", "excerpt": "La empresa restableció el servicio en la capital."},
    ]
    schema = research.answer_schema(evidence, global_compare=True)
    result = schema.model_validate({"status": "answered", "limitations": "Timing is unclear.", "claims": [
        {"kind": "shared", "text": "The operator restored service in the capital.", "source_ids": ["one", "two"],
         "quotes": ["restored service in the capital", "restableció el servicio en la capital"]}]})
    with pytest.raises(ValueError, match="distinct evidence"):
        research.validate_answer(result, evidence)
    evidence[1]["publisher_family"] = "other-publisher"
    assert research.validate_answer(result, evidence)["claims"][0]["kind"] == "shared"


def test_technical_brief_uses_typed_sections_and_publisher_quotes(tmp_path, monkeypatch):
    import json
    from app import research

    store = Store(f"sqlite:///{tmp_path / 'technical.sqlite'}")
    evidence = [{"id": "release", "title": "New release", "excerpt": "The release removes the old cache adapter and documents a replacement."}]
    monkeypatch.setattr(research, "ai_enabled", lambda: True)

    def model(payload, system, schema, *, max_tokens):
        assert "Do not infer a breaking change" in system
        return json.dumps({"status": "answered", "limitations": "The excerpt does not list the migration steps.", "claims": [
            {"kind": "breaking", "source_id": "release", "quote": "removes the old cache adapter", "text": "The release removes the old cache adapter."}]})

    monkeypatch.setattr(ai_insights, "generate_response", model)
    answer = ai_insights.technical_brief(store, evidence, "release", "en")
    assert answer["claims"][0]["kind"] == "breaking"
    assert ai_insights.technical_brief(store, evidence, "release", "en")["cached"]


def test_explicit_feedback_affects_both_reading_and_email(tmp_path):
    from app.intelligence import recommend
    from app.reader_signals import ReaderFeedback

    store = Store(f"sqlite:///{tmp_path / 'feedback.sqlite'}")
    rows = [
        story("liked", "Kubernetes publishes deployment guide", "Techniques for operating Kubernetes services.", "ars-technica"),
        story("company", "NVIDIA publishes GPU architecture notes", "NVIDIA released a hardware explanation.", "the-verge"),
    ]
    for row in rows:
        store.ingest(row["source_id"], [row], True)
        event_intelligence.observe(store, row)
    pool = event_intelligence.catalog(store)
    company = next(event for event in pool if event["articles"][0]["id"] == "company")
    other = next(event for event in pool if event["articles"][0]["id"] == "liked")
    feedback = ReaderFeedback(companies=["NVIDIA"])
    ranked = recommend(store.pinned_articles(["liked", "company"]), companies=feedback.companies)
    assert ranked["articles"][0]["id"] == "company"
    assert "a company you follow" in ranked["articles"][0]["recommendation_reasons"][0]
    profile = ai_insights.RadarProfile(feedback=feedback)
    assert ai_insights.rank_events(pool, profile, {})[0]["id"] == company["id"]
    profile.feedback.muted_topics = [other["articles"][0]["topic"]]
    brief = ai_insights.catchup(store, profile, {}, pool=pool, allow_generate=False)
    assert other["id"] not in {event["id"] for event in brief["events"]}


def test_conversation_retrieves_prior_source_context_but_keeps_provider_fallback(tmp_path, monkeypatch):
    from app import insight_api
    from app.launch_store import Store
    from starlette.requests import Request
    from starlette.responses import Response

    store = Store(f"sqlite:///{tmp_path / 'conversation.sqlite'}")
    store.migrate()
    row = story("conversation-1", "Cloud network disruption affects API access",
        "A cloud provider reported network disruption affecting API availability.", "ars-technica")
    store.ingest(row["source_id"], [row], True)
    monkeypatch.setattr(insight_api, "get_store", lambda: store)
    ident, _ = event_intelligence.observe(store, row)
    from app import server
    monkeypatch.setattr(server, "get_store", lambda: store)
    assert server.article_details("conversation-1", Response())["development_id"] == ident
    request = Request({"type": "http", "method": "POST", "path": "/api/intelligence/converse",
        "headers": [(b"user-agent", b"test")], "client": ("127.0.0.1", 8080), "scheme": "http", "query_string": b""})
    result = insight_api.converse(insight_api.ConversationRequest.model_validate({
        "question": "What happened next?", "history": [{"role": "user", "content": "Cloud API outage"}],
        "context_ids": ["conversation-1"], "hours": 168, "topic": "all", "language": "en",
    }), request, Response())
    assert result["evidence"][0]["id"] == "conversation-1"
    assert result["answer"]["status"] == "unavailable"
    assert result["answer"]["limitations"]

    # In-reader questions must not retrieve unrelated archive stories.
    from app import research
    def reject_search(*args, **kwargs):
        raise AssertionError("Story-scoped questions must use supplied source context")
    monkeypatch.setattr(research, "lexical_results", reject_search)
    monkeypatch.setattr(research, "vector_results", reject_search)
    scoped = insight_api.converse(insight_api.ConversationRequest.model_validate({
        "question": "Which APIs were affected?", "context_ids": ["conversation-1"], "context_only": True,
    }), request, Response())
    assert [row["id"] for row in scoped["evidence"]] == ["conversation-1"]
    assert scoped["retrieval"] == "source_context"


def test_opted_in_radar_gets_personalized_morning_mail_and_history_after_acceptance(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from app import ai_insights, mail_batches, public_mail

    store = Store(f"sqlite:///{tmp_path / 'scheduled-radar.sqlite'}")
    store.migrate()
    row = story("morning-cloud", "Cloud provider reports a regional network outage",
        "The cloud provider said network disruption affected regional API availability.", "ars-technica")
    store.ingest(row["source_id"], [row], True)
    event_intelligence.observe(store, row)
    email = "reader@example.org"
    monkeypatch.setenv("MAIL_SESSION_SECRET", "test-only-radar-secret")
    mailbox = public_mail.digest_key("mailbox:" + email)
    store.subscribe(mailbox, email, "UTC", time.time() - 10)
    radar_store.save_profile(store, mailbox, ai_insights.RadarProfile(role="engineer", interests=["cloud"]).model_dump())
    response = Mock(status_code=200, is_success=True)
    response.json.return_value = {"data": [{"id": "resend-accepted"}]}
    monkeypatch.setattr(mail_batches.httpx, "post", Mock(return_value=response))
    monkeypatch.setattr(mail_batches.time, "sleep", lambda *_: None)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("MAIL_FROM", "brief@example.org")
    result = mail_batches.run_batch_worker(store, lambda: {"html": "global", "markdown": "global"})
    sent_payload = mail_batches.httpx.post.call_args.kwargs["json"][0]
    assert result["sent"] == 1
    assert "Cloud provider reports a regional network outage" in sent_payload["text"]
    assert not any(key.startswith("_informa") for key in sent_payload)
    assert radar_store.histories(store, [mailbox])[mailbox]


def test_catchup_and_development_search_return_meaningful_changes_over_http(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import insight_api, server

    store = Store(f"sqlite:///{tmp_path / 'material.sqlite'}")
    store.migrate()
    now = time.time()
    report = story("cloud-1", "Northstar cloud network outage disrupts regional services",
                   "A disruption affected service availability.", "ars-technica")
    repeat = story("cloud-2", report["title"], "Regional service availability was disrupted.", "the-verge")
    for row in (report, repeat):
        store.ingest(row["source_id"], [row], True)
    event, _ = event_intelligence.observe(store, report, now=now - 30)
    event_intelligence.observe(store, repeat, now=now - 20)
    cosmetic = dict(report, description="A disruption affected service availability. Read more on our website.")
    event_intelligence.observe(store, cosmetic, now=now - 15)
    uncertain = dict(report, description="The incident was not resolved. The operator is investigating.")
    event_intelligence.observe(store, uncertain, now=now - 10)
    assert event_intelligence.timeline(store, event, since=1)["changes"] == []

    monkeypatch.setattr(insight_api, "get_store", lambda: store)
    client = TestClient(server.app)
    payload = {"hours": 720, "since": now - 25, "summary_only": True}
    assert client.post("/api/intelligence/catchup", json=payload).json()["events"] == []
    revised = dict(report, description="The provider says service has been restored.")
    event_intelligence.observe(store, revised, now=now - 5)
    response = client.post("/api/intelligence/catchup", json=payload)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert "preview" not in data
    update = data["events"][0]
    assert update["change"] == "updated"
    assert update["change_sources"][0]["change_label"] == "Resolved"
    assert update["change_sources"][0]["excerpt"] == revised["description"]
    assert update["change_sources"][0]["url"] == report["url"]
    assert client.get("/api/intelligence/events", params={"q": "Northstar outage", "hours": 12}).json()["events"][0]["id"] == event
    assert client.get("/api/intelligence/events", params={"q": "Northstar satellites", "hours": 12}).json()["events"] == []


def test_followed_updates_mail_skips_unrelated_reports_and_repeat_coverage(tmp_path):
    from app import mail_schedule

    store = Store(f"sqlite:///{tmp_path / 'followed.sqlite'}")
    store.migrate()
    mailbox = "b" * 64
    row = story("gpu-news", "NVIDIA publishes new GPU driver compatibility details",
                "NVIDIA announced new driver requirements.", "ars-technica")
    unrelated = story("cloud-news", "Cloud provider rebuilds billing dashboard",
                      "The company redesigned its customer site.", "the-verge")
    for article in (row, unrelated):
        store.ingest(article["source_id"], [article], True)
        event_intelligence.observe(store, article)
    profile = ai_insights.RadarProfile(delivery_mode="material_updates", feedback={"companies": ["NVIDIA"]})
    radar_store.save_profile(store, mailbox, profile.model_dump())
    def load():
        return event_intelligence.catalog(store)
    brief = mail_schedule.personalized_morning_brief(store, mailbox, {}, load)
    assert brief["followed_updates"] is True
    assert [item["digest_id"] for item in brief["articles"]] == ["gpu-news"]
    assert "Mentions a company you follow: NVIDIA" in brief["markdown"]
    assert "Manage or mute follows" in brief["html"]
    store.reserve_delivery("followed-delivery", [("mail:followed", "today", 3)],
                           event_mailbox=mailbox, event_history=brief["_catchup"])
    store.record_delivery("followed-delivery", "provider-accepted")
    assert mail_schedule.personalized_morning_brief(store, mailbox, {}, load) is None
