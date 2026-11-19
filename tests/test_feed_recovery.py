import socket
import ssl
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException

from app import ingestion, news, server
from app.launch_store import Store
from app.sources import BY_ID, DEFAULT_SOURCES


def test_configured_pause_overrides_preexisting_enabled_state(tmp_path, monkeypatch):
    source = replace(BY_ID["bbc-tech"], enabled=False)
    monkeypatch.setattr(ingestion, "DEFAULT_SOURCES", (source,))
    store = Store(f"sqlite:///{tmp_path / 'feed-recovery.db'}")
    store.ingest(source.id, [], False, "access_denied")
    assert store.source_state()[source.id]["enabled"] is True
    monkeypatch.setattr(ingestion, "read_feed", lambda *args, **kwargs: pytest.fail("Paused source fetched"))

    now = datetime.now(UTC)
    assert ingestion.sweep_plan(store.source_state(), ingestion.latest_sweep(now), now) == (set(), {})
    assert ingestion.refresh_plan(store.source_state(), only=source.id) == []
    feed, = ingestion.refresh_sources(store)
    assert feed["freshness"] == "paused"
    assert feed["next_check_at"] is None
    assert ingestion.feed_freshness([feed])["counts"]["enabled"] == 0


def test_owner_cannot_enable_a_connector_paused_in_the_registry(monkeypatch):
    source = BY_ID["tech-in-asia"]
    monkeypatch.setattr(server, "BY_ID", {source.id: replace(source, enabled=False)})
    monkeypatch.setenv("ADMIN_TOKEN", "owner-key-for-tests")
    monkeypatch.setattr(server, "source_store", lambda: pytest.fail("Paused source was changed"))
    with pytest.raises(HTTPException) as caught:
        server.update_source(source.id, server.SourceUpdate(enabled=True), "Bearer owner-key-for-tests")
    assert caught.value.status_code == 409


def test_paused_connectors_keep_reasons_and_coverage_alternatives():
    paused = ("tech-in-asia", "hashnode-discover", "venturebeat", "venturebeat-news-index", "moneycontrol-it", "robohub")
    assert all(not BY_ID[key].enabled and BY_ID[key].pause_reason for key in paused)
    active = [source for source in DEFAULT_SOURCES if source.enabled]
    assert len(active) >= 501
    for key in ("govtech-singapore", "open-robotics-discourse", "techxplore-robotics",
                "release-mistral-vibe", "release-pytorch-executorch", "release-langflow"):
        replacement = BY_ID[key]
        assert [source.id for source in active if source.url == replacement.url] == [key]
    for key in ("tnglobal", "hashnode", "crossref-nature-mi", "nature-machine-intelligence",
                "moneycontrol-tech", "moneycontrol-news-index", "techxplore-robotics"):
        assert BY_ID[key].enabled


@pytest.mark.parametrize(("error", "cause", "code"), [
    (TimeoutError(), None, "fetch_timeout"),
    (httpx.ReadTimeout("read timeout"), None, "fetch_timeout"),
    (httpx.ConnectError("cannot resolve"), socket.gaierror(), "dns_failed"),
    (httpx.ConnectError("certificate error"), ssl.SSLError(), "tls_failed"),
    (httpx.ConnectError("connection refused"), None, "connection_failed"),
])
def test_rss_transport_failures_keep_an_actionable_safe_code(monkeypatch, error, cause, code):
    def fail(_):
        raise error from cause

    monkeypatch.setattr(news, "fetch_bytes", fail)
    rows, state = news.read_feed(BY_ID["nature-machine-intelligence"])
    assert not rows and not state["available"]
    assert state["error"] == code
