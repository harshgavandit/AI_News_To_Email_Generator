"""Anonymous catch-up windows and evidence-only reads use a disposable archive."""

from datetime import UTC, datetime, timedelta
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app import event_intelligence, insight_api, research, server, visit_catchup
from app.launch_store import Store, limits
from app.sources import BY_ID

NOW = datetime(2026, 11, 18, 10, tzinfo=UTC)
ENDPOINT = "/api/intelligence/visit-catchup"


@pytest.fixture
def archive(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'visit.db'}")
    store.migrate()
    monkeypatch.setattr(insight_api, "get_store", lambda: store)
    real_window = visit_catchup.visit_window
    monkeypatch.setattr(visit_catchup, "visit_window", lambda body: real_window(body, NOW))
    yield store, TestClient(server.app)
    store.engine.dispose()


def publish(store, ident, title, *, hours=4, feed="the-verge", url=None, excerpt=None):
    source = BY_ID[feed]
    path = source.article_paths[0] if source.article_paths else "/"
    row = {"id": ident, "title": title, "description": excerpt or "The publisher reported this development.",
           "url": url or f"https://{source.hosts[0]}{path}{ident}", "source": source.group, "source_id": source.id,
           "publisher": source.label, "kind": source.kind, "category": "Technology",
           "published_at": (NOW - timedelta(hours=hours)).isoformat()}
    store.ingest(source.id, [row], True)
    return row


def test_monitor_timestamps_distinguish_publication_first_observation_and_update(archive, monkeypatch):
    store, client = archive
    recent = publish(store, "current", "Google launches new database tooling")
    late = publish(store, "late", "Chipmaker announces new board appointments", hours=32, feed="bbc-tech")
    outage = publish(store, "outage", "Cloud service outage disrupts regional workloads", hours=44, feed="ars-technica")
    repeated = publish(store, "repeated", "New tools announced at industry conference", hours=50, feed="wired")
    disabled = publish(store, "disabled", "Oracle launches a new cloud region", hours=1, feed="9to5google")
    publish(store, "readme", "An article on async JavaScript", hours=2, feed="dev-community")
    store.enable(disabled["source_id"], False)

    recent_event, _ = event_intelligence.observe(store, recent, now=(NOW - timedelta(hours=3)).timestamp())
    late_event, _ = event_intelligence.observe(store, late, now=(NOW - timedelta(hours=2)).timestamp())
    outage_event, _ = event_intelligence.observe(store, outage, now=(NOW - timedelta(hours=40)).timestamp())
    revised = {**outage, "title": "Cloud service outage resolved in two European regions",
               "description": "The operator reported that services were restored in two regions."}
    store.ingest(revised["source_id"], [revised], True)
    event_intelligence.observe(store, revised, now=(NOW - timedelta(hours=1)).timestamp())
    event_intelligence.observe(store, repeated, now=(NOW - timedelta(hours=48)).timestamp())
    event_intelligence.observe(store, repeated, now=(NOW - timedelta(minutes=45)).timestamp())

    def unexpected(*args, **kwargs):
        pytest.fail("A source-only catch-up must never ask a model")

    monkeypatch.setattr(research, "synthesize", unexpected)
    response = client.post(ENDPOINT, json={})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers
    result = response.json()
    assert result["since"] == (NOW - timedelta(hours=24)).isoformat()
    assert result["as_of"] == NOW.isoformat()
    assert result["window"] == "first_visit" and result["answer"] is None
    evidence = {row["id"]: row for row in result["evidence"]}
    assert set(evidence) == {"current", "late", "outage"}
    assert evidence["current"]["change_type"] == "published"
    assert evidence["current"]["event_id"] == recent_event
    assert evidence["late"]["change_type"] == "newly_observed"
    assert evidence["late"]["event_id"] == late_event
    assert evidence["late"]["observed_at"] == (NOW - timedelta(hours=2)).isoformat()
    assert evidence["late"]["published_at"] == late["published_at"]
    assert evidence["outage"]["change_type"] == "event_update"
    assert evidence["outage"]["event_id"] == outage_event
    assert evidence["outage"]["update_reason"] == "source_revision"
    assert evidence["outage"]["title"] == revised["title"]
    assert evidence["outage"]["excerpt"] == revised["description"]
    with store.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(limits)) == 0


def test_time_fence_excludes_outside_reports_and_preserves_first_snapshot(archive):
    store, client = archive
    after_end = publish(store, "after", "Nvidia launches a new chip", hours=1)
    in_scope = publish(store, "in", "Nvidia posts quarterly results", hours=4)
    before_start = publish(store, "before", "Nvidia announces an earlier event", hours=170)
    for row, observed in [(after_end, 0.5), (in_scope, 3.5), (before_start, 170.5)]:
        event_intelligence.observe(store, row, now=(NOW - timedelta(hours=observed)).timestamp())
    store.ingest(in_scope["source_id"], [in_scope | {"title": "Future revision not yet known"}], True)
    newer = in_scope | {"title": "Future revision not yet known"}
    event_intelligence.observe(store, newer, now=(NOW - timedelta(hours=1)).timestamp())
    response = client.post(ENDPOINT, json={"since": "2020-01-01T00:00:00Z", "as_of": "2026-11-18T08:00:00Z"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["since"] == (NOW - timedelta(days=7, hours=2)).isoformat()
    assert data["as_of"] == "2026-11-18T08:00:00+00:00" and data["window"] == "clamped"
    assert [(record["id"], record["title"]) for record in data["evidence"]] == [("in", in_scope["title"])]


@pytest.mark.parametrize("body", [
    {"since": "2026-11-18"}, {"since": "2026-11-18T09:00:00"},
    {"since": "2026-11-18T09:00:00+05:30"}, {"since": 1763456400},
    {"since": "2026-11-18T11:00:00Z"}, {"as_of": "2026-11-18T11:00:00Z"},
    {"as_of": "2026-10-18T11:00:00Z"}, {"analyze": "true"}, {"user_id": "unexpected"},
])
def test_invalid_interval_and_unexpected_identity_are_rejected(archive, body):
    _, client = archive
    assert client.post(ENDPOINT, json=body).status_code == 422


def test_explicit_synthesis_validates_citations_and_retains_evidence_on_failure(archive, monkeypatch):
    store, client = archive
    row = publish(store, "launch", "A chipmaker launches an enterprise processor",
                  excerpt="The processor ships to enterprise customers this month.")
    body = {"analyze": True, "since": "2026-11-18T00:00:00Z", "as_of": NOW.isoformat()}
    disabled = client.post(ENDPOINT, json=body).json()
    assert disabled["answer"]["status"] == "unavailable"
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("NEWS_AI_RESEARCH", "1")
    monkeypatch.setattr(research, "generate_response", lambda *args, **kwargs: json.dumps({
        "status": "answered", "claims": [{"kind": "fact", "text": "A different claim.", "source_ids": ["invented"],
            "quotes": [row["description"]]}],
        "limitations": "Based on supplied reporting."}))
    rejected = client.post(ENDPOINT, json=body).json()
    assert rejected["answer"]["status"] == "unavailable"
    assert rejected["evidence"] == disabled["evidence"]

    monkeypatch.setattr(research, "generate_response", lambda *args, **kwargs: json.dumps({
        "status": "answered", "claims": [{"kind": "fact", "text": "An unsupported claim.",
            "source_ids": [row["id"]], "quotes": ["A quotation absent from the source excerpt."]}],
        "limitations": "Based on the publisher excerpt."}))
    rejected = client.post(ENDPOINT, json=body).json()
    assert rejected["answer"]["status"] == "unavailable"
    assert rejected["evidence"] == disabled["evidence"]

    def respond(payload, _system, schema, **_kwargs):
        request = json.loads(payload)
        assert request["task"] == "visit_catchup"
        assert [item["id"] for item in request["evidence"]] == [row["id"]]
        quote_schema = schema.model_json_schema()["$defs"]["ResearchClaim"]["properties"]["quotes"]["items"]
        assert quote_schema == {"const": row["description"], "type": "string"}
        return json.dumps({"status": "answered", "claims": [{"kind": "fact", "text": row["description"],
            "source_ids": [row["id"]], "quotes": [row["description"]]}], "limitations": "Based on the publisher excerpt."})

    monkeypatch.setattr(research, "generate_response", respond)
    answer = client.post(ENDPOINT, json=body).json()
    assert answer["window"] == "since_visit" and answer["answer"]["status"] == "answered"
    assert answer["answer"]["claims"][0]["source_ids"] == [row["id"]]
    assert answer["evidence"] == disabled["evidence"]


def test_evidence_falls_back_to_publications_when_event_index_is_unavailable(archive, monkeypatch):
    store, client = archive
    monkeypatch.setattr(event_intelligence, "ready", lambda store: False)
    article = publish(store, "current", "Google debuts a cloud release")
    publish(store, "older", "A previous outage was resolved", hours=72)
    response = client.post(ENDPOINT, json={})
    assert response.status_code == 200
    result = response.json()["evidence"]
    assert [record["id"] for record in result] == [article["id"]]
    assert result[0]["observed_at"] is None and result[0]["event_id"] is None


def test_evidence_is_bounded_and_collapses_event_alternates_and_canonical_links(archive):
    store, client = archive
    title = "Microsoft launches enterprise networking service for European cloud customers"
    anchor = publish(store, "anchor", title, hours=8)
    duplicate = publish(store, "duplicate", title, hours=7, feed="bbc-tech", url=anchor["url"])
    followup = publish(store, "followup", title, hours=6, feed="ars-technica")
    for offset, row in enumerate([anchor, duplicate, followup]):
        event_id, _ = event_intelligence.observe(store, row, now=(NOW - timedelta(hours=5 - offset)).timestamp())
        if offset == 0:
            expected_event = event_id
        assert event_id == expected_event
    for i, feed in enumerate(("wired", "techcrunch", "9to5google", "the-verge", "tech-eu", "bbc-tech", "scmp-tech", "itnews-au")):
        publish(store, f"other-{i}", f"Cloud security policy released for region {i}", hours=12, feed=feed)
    evidence = client.post(ENDPOINT, json={}).json()["evidence"]
    assert len(evidence) == visit_catchup.EVIDENCE_LIMIT
    assert sum(item["event_id"] == expected_event for item in evidence) == 1
    assert len({item["url"] for item in evidence}) == len(evidence)


def test_unindexed_near_duplicates_do_not_hide_distinct_developments(archive):
    store, client = archive
    title = "Microsoft launches enterprise networking service for European cloud customers"
    launch = publish(store, "launch", title, hours=1)
    publish(store, "copy-link", "A title changed by another feed", hours=3, feed="bbc-tech", url=launch["url"])
    publish(store, "same-event", title + " today", hours=2, feed="ars-technica")
    publish(store, "distinct-event", "Microsoft discloses a cloud data breach in Europe", hours=4, feed="wired")
    evidence = client.post(ENDPOINT, json={}).json()["evidence"]
    assert {item["id"] for item in evidence} == {"launch", "distinct-event"}
