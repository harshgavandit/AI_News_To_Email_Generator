"""Event grouping and private radar-history regressions."""
from datetime import UTC, datetime, timedelta
import time
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
    import pytest
    with pytest.raises(ValueError):
        ai_insights.validate_explanation(invalid_quote, evidence)


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
    request = Request({"type": "http", "method": "POST", "path": "/api/intelligence/converse",
        "headers": [(b"user-agent", b"test")], "client": ("127.0.0.1", 8080), "scheme": "http", "query_string": b""})
    result = insight_api.converse(insight_api.ConversationRequest.model_validate({
        "question": "What happened next?", "history": [{"role": "user", "content": "Cloud API outage"}],
        "context_ids": ["conversation-1"], "hours": 168, "topic": "all", "language": "en",
    }), request, Response())
    assert result["evidence"][0]["id"] == "conversation-1"
    assert result["answer"]["status"] == "unavailable"
    assert result["answer"]["limitations"]


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
