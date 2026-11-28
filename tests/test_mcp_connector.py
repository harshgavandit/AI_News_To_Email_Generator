import asyncio
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest
from sqlalchemy import event

from app import ask, mcp_connector, research, server, trackers, weekly_recap
from app.cache import Cache
from app.launch_store import Store
from scripts.check_reader_quality import fixture_row
from test_ask import fake_model

HOST = "http://localhost"
HEADERS = {
    "accept": "application/json, text/event-stream",
    "mcp-protocol-version": "2025-06-18",
}


@pytest.fixture
def archive(research_database, monkeypatch):
    store = Store(research_database)
    store.migrate()
    recent = (datetime.now(UTC) - timedelta(minutes=15)).timestamp()
    week = weekly_recap.last_complete_week()
    last_week = weekly_recap.week_bounds(week)[0] + timedelta(days=2)
    excerpt = "The Borealis outage interrupted the storage API for 25 minutes."
    title = "Borealis cloud outage interrupts European storage API"
    for ident, stamp, feed, headline, text in [
        ("borealis", recent, "ars-technica", title, excerpt),
        ("borealis-verge", recent - 600, "the-verge", title, excerpt),
        (
            "gcp-inc",
            recent,
            "google-cloud-status",
            "Google Cloud service disruption resolved",
            "Google Cloud restored its storage service following a disruption.",
        ),
        (
            "last-week",
            last_week.timestamp(),
            "wired",
            "Cascade raises funding for inference chips",
            "Cascade raised new funding to manufacture inference chips.",
        ),
    ]:
        story = fixture_row({"title": headline, "source_id": feed}, ident, text, stamp)
        store.ingest(feed, [story], True)
    assert weekly_recap.prepare(store) in {"ready", "partial"}
    for module in (ask, mcp_connector, server, trackers, weekly_recap):
        monkeypatch.setattr(module, "get_store", lambda: store)
    monkeypatch.setattr(ask, "_cache", Cache("mcp-test-ask"))
    monkeypatch.setattr(mcp_connector, "_cache", Cache("mcp-test-public"))
    monkeypatch.setattr(trackers, "_tracker_cache", Cache("mcp-test-tracker"))
    monkeypatch.setattr(server, "_limits", OrderedDict())
    monkeypatch.setattr(research, "vectors_enabled", lambda: False)
    monkeypatch.setattr(research, "ai_enabled", lambda: True)
    monkeypatch.setattr(research, "generate_response", fake_model([]))
    yield store
    store.engine.dispose()


def rpc(client, method, params=None, *, headers=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post("/mcp", json=payload, headers={**HEADERS, **(headers or {})})


def test_official_client_discovers_and_calls_all_tools_with_no_startup_lifespan(
    archive, monkeypatch,
):
    from app import watch_agent
    from scripts.watch_evals import judge_stub

    def watch_model(store, payload, prompt, schema, task, timeout):
        if task == "watch_agent_draft":
            return watch_agent.Proposal(watch=watch_agent.Spec(
                summary="Borealis storage outage", topics=["outages"], entities=["Borealis"],
                keywords=["outage"], must_have=["outage"], exclude=[], severity="any",
            )).model_dump_json()
        return judge_stub(store, payload, prompt, schema, task, timeout)

    monkeypatch.setattr(watch_agent, "model_call", watch_model)
    statements = []

    @event.listens_for(archive.engine, "before_cursor_execute")
    def record_sql(_conn, _cursor, statement, *_):
        statements.append(statement.casefold())

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url=HOST,
        ) as http:
            async with streamable_http_client(f"{HOST}/mcp", http_client=http) as (
                read,
                write,
                session_id,
            ):
                async with ClientSession(read, write) as session:
                    assert (await session.initialize()).serverInfo.name == "Informa AI"
                    assert session_id() is None
                    assert await session.send_ping()
                    listing = await session.list_tools()
                    assert len(listing.tools) == 10
                    assert {tool.name for tool in listing.tools} == {
                        "search_news",
                        "get_story",
                        "latest_headlines",
                        "get_tracker",
                        "curiosity_cards",
                        "weekly_recap",
                        "ask_informa",
                        "deep_research",
                        "list_watch_examples",
                        "preview_watch",
                    }
                    for tool in listing.tools:
                        assert tool.inputSchema["additionalProperties"] is False
                        assert (
                            tool.annotations is not None
                            and tool.annotations.readOnlyHint
                        )
                    scenarios = {
                        "search_news": (
                            {"query": "Borealis outage", "limit": 1},
                            "stories",
                        ),
                        "get_story": ({"id": "borealis"}, "coverage"),
                        "latest_headlines": ({"limit": 1}, "developing"),
                        "get_tracker": ({"name": "incidents"}, "items"),
                        "curiosity_cards": ({"limit": 1}, "cards"),
                        "weekly_recap": ({}, "top_stories"),
                        "ask_informa": (
                            {
                                "question": "Which API did the Borealis outage interrupt?"
                            },
                            "citations",
                        ),
                    }
                    for name, (args, field) in scenarios.items():
                        result = await session.call_tool(name, args)
                        assert not result.isError, (name, result.content)
                        payload = result.structuredContent
                        assert payload and payload[field], name
                        assert payload["informa_url"].startswith(
                            "https://getinformdaily.com/"
                        )
                        if name == "get_story":
                            assert payload["coverage"][0]["publisher"] == "The Verge"
                        if name == "get_tracker":
                            assert (
                                payload["items"]["providers"][0]["source_id"]
                                == "google-cloud-status"
                            )
                        if name == "ask_informa":
                            assert payload["status"] == "answered"
                            assert payload["citations"][0]["id"] in {
                                "borealis",
                                "borealis-verge",
                            }
                    examples = await session.call_tool("list_watch_examples", {})
                    assert examples.structuredContent["examples"]
                    preview = await session.call_tool("preview_watch", {"sentence": "Watch for Borealis storage outages."})
                    assert not preview.isError
                    assert preview.structuredContent["status"] == "ready"
                    assert len(preview.structuredContent["matches"]) == 1
                    assert preview.structuredContent["matches"][0]["source_checked"]
                    refusal = await session.call_tool("preview_watch", {"sentence": "Tell me football scores."})
                    assert refusal.structuredContent["status"] == "refused"

    asyncio.run(exercise())
    assert statements
    assert not any(
        name in statement
        for name in (
            "brief_mail_",
            "brief_subscriptions",
            "brief_verification",
            "brief_feedback",
            "brief_research_projects",
            "brief_monitor_",
            "brief_watch_agent_",
            "brief_send",
        )
        for statement in statements
    )


@pytest.mark.parametrize(
    "name,args",
    [
        ("search_news", {"query": "Borealis", "days": 31}),
        ("search_news", {"query": "Borealis", "region": "unknown"}),
        ("search_news", {"query": "Borealis", "topic": "unknown"}),
        ("search_news", {"query": "test@example.org"}),
        ("latest_headlines", {"limit": "1"}),
        ("latest_headlines", {"limit": 21}),
        ("get_story", {"id": "../../admin"}),
        ("get_story", {"id": "borealis", "include_private": True}),
        ("get_tracker", {"name": "subscribers"}),
        ("curiosity_cards", {"limit": 13}),
        ("weekly_recap", {"week": "2026-W99"}),
        ("preview_watch", {"sentence": "Track Borealis outages.", "profile_id": "private"}),
        ("get_private_watches", {}),
        ("send_email", {"recipient": "test@example.org"}),
    ],
)
def test_invalid_arguments_return_safe_mcp_errors(archive, name, args):
    with TestClient(server.app, base_url=HOST) as client:
        response = rpc(client, "tools/call", {"name": name, "arguments": args})
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True
    assert "test@example.org" not in response.text


def test_mcp_transport_enforces_origin_host_and_rate_limits(archive):
    with TestClient(server.app, base_url=HOST) as client:
        bad_origin = rpc(client, "ping", headers={"origin": "https://other.example"})
        assert bad_origin.status_code == 403
        bad_host = rpc(client, "ping", headers={"host": "other.example"})
        assert bad_host.status_code == 421
        for _ in range(119):
            assert rpc(client, "ping").status_code == 200
        blocked = rpc(client, "ping")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_ask_tool_and_web_use_the_same_budget(archive):
    with TestClient(server.app, base_url=HOST) as client:
        question = {"question": "Which API did the Borealis outage interrupt?"}
        for _ in range(10):
            assert client.post("/api/ask", json=question).status_code == 200
        response = rpc(
            client, "tools/call", {"name": "ask_informa", "arguments": question}
        )
    assert "Retry after" in response.text
    assert response.json()["result"]["isError"] is True
