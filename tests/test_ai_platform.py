"""AI gateway routing, fallback, usage accounting, budgets and natural-language search."""
import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AuthenticationError, NotFoundError
from unittest.mock import Mock

from app import ai_usage, research, server
from app.agent import openai_client
from app.coverage import REGION_LABELS, TOPICS
from app.discovery import COVERAGE_TYPES
from app.intelligence import SUBJECTS
from app.launch_store import Store
from app.query_understanding import understand
from app.sources import BY_ID

OWNER = "owner-token-for-ai-platform-tests-0123456"


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'ai.sqlite'}")
    store.migrate()
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr("app.launch_store.get_store", lambda: store)
    for name in ("NEWS_AI_MODEL_FAST", "NEWS_AI_MODEL_STANDARD", "NEWS_AI_MODEL_DEEP", "NEWS_AI_ANALYSIS_MODEL",
                 "NEWS_AI_FALLBACK_MODEL", "NEWS_AI_DAILY_BUDGET_USD", "NEWS_AI_PRICES", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    ai_usage._spend.update(day=None, usd=0.0, checked=0.0)
    yield store
    store.engine.dispose()


def status_error(cls, status, code=None):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return cls("no", response=httpx.Response(status, request=request), body={"code": code} if code else None)


def fake_client(behaviour):
    """behaviour(model) returns content or raises; usage is reported for successes."""
    calls = []

    def create(**options):
        calls.append(options["model"])
        content = behaviour(options["model"])
        return Mock(choices=[Mock(message=Mock(content=content))], usage=Mock(prompt_tokens=1000, completion_tokens=500))

    return Mock(chat=Mock(completions=Mock(create=create))), calls


def test_tasks_route_to_tiers_with_overrides(store, monkeypatch):
    assert openai_client.route_model("explain") == openai_client.route_model("compare") == "gpt-4o-mini"
    monkeypatch.setenv("OPENAI_MODEL", "base-model")
    monkeypatch.setenv("NEWS_AI_MODEL_FAST", "fast-model")
    monkeypatch.setenv("NEWS_AI_ANALYSIS_MODEL", "legacy-analysis")
    assert openai_client.route_model("explain") == "fast-model"
    assert openai_client.route_model("analyze") == "base-model"
    assert openai_client.route_model("global_compare") == "legacy-analysis"
    monkeypatch.setenv("NEWS_AI_MODEL_DEEP", "deep-model")
    assert openai_client.route_model("compare") == "deep-model"
    assert openai_client.route_model("unknown-task") == "base-model"


def test_unavailable_model_falls_back_and_usage_is_recorded(store, monkeypatch):
    monkeypatch.setenv("NEWS_AI_MODEL_DEEP", "gpt-4o")

    def behaviour(model):
        if model == "gpt-4o":
            raise status_error(NotFoundError, 404)
        return "{}"

    client, calls = fake_client(behaviour)
    monkeypatch.setattr(openai_client, "get_client", lambda: client)
    assert openai_client.generate_response("x", task="compare") == "{}"
    assert calls == ["gpt-4o", "gpt-4o-mini"]
    rows = {(row["task"], row["model"]): row for row in ai_usage.summary(store)}
    assert rows[("compare", "gpt-4o")]["failures"] == 1
    success = rows[("compare", "gpt-4o-mini")]
    assert (success["calls"], success["prompt"], success["completion"]) == (1, 1000, 500)
    assert success["estimated_usd"] == pytest.approx((1000 * 0.15 + 500 * 0.60) / 1_000_000)


def test_authentication_errors_do_not_fall_back(store, monkeypatch):
    def behaviour(model):
        raise status_error(AuthenticationError, 401)

    client, calls = fake_client(behaviour)
    monkeypatch.setattr(openai_client, "get_client", lambda: client)
    with pytest.raises(AuthenticationError):
        openai_client.generate_response("x", task="analyze")
    assert calls == ["gpt-4o-mini"]


def test_daily_budget_stops_calls_and_is_reported_as_budget_limited(store, monkeypatch):
    client, calls = fake_client(lambda model: "{}")
    monkeypatch.setattr(openai_client, "get_client", lambda: client)
    ai_usage.record("analyze", "gpt-4o", 1_000_000, 0, store=store)  # $2.50 estimated
    monkeypatch.setenv("NEWS_AI_DAILY_BUDGET_USD", "2")
    with pytest.raises(openai_client.BudgetExceeded) as error:
        openai_client.generate_response("x")
    assert calls == [] and research.classify_provider_error(error.value) == "budget_limited"
    monkeypatch.setenv("NEWS_AI_DAILY_BUDGET_USD", "5")
    ai_usage._spend.update(checked=0.0)
    assert openai_client.generate_response("x") == "{}"


def test_prices_cover_dated_snapshots_and_overrides(monkeypatch):
    assert ai_usage.price_for("gpt-4o-mini-2024-07-18") == ai_usage.DEFAULT_PRICES["gpt-4o-mini"]
    assert ai_usage.estimate("unknown-model", 10, 10) is None
    monkeypatch.setenv("NEWS_AI_PRICES", '{"unknown-model": [1, 2]}')
    assert ai_usage.estimate("unknown-model", 1_000_000, 1_000_000) == 3.0
    monkeypatch.setenv("NEWS_AI_PRICES", "not json")
    assert ai_usage.estimate("gpt-4o", 0, 0) == 0.0


def test_owner_ai_usage_report(store, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", OWNER)
    ai_usage.record("explain", "gpt-4o-mini", 2000, 100, store=store)
    ai_usage.record("explain", "gpt-4o-mini", 0, 0, ok=False, store=store)
    client = TestClient(server.app)
    assert client.get("/api/admin/ai-usage").status_code == 401
    data = client.get("/api/admin/ai-usage", headers={"Authorization": f"Bearer {OWNER}"}).json()
    today, = data["days"]
    assert (today["calls"], today["failures"], today["prompt"]) == (2, 1, 2000)
    assert data["routing"]["fast"] == "gpt-4o-mini" and data["tasks"]["compare"] == "deep"
    assert data["spend_today_usd"] == pytest.approx(today["estimated_usd"])


def interpret(query):
    return understand(query, topics=TOPICS, regions=REGION_LABELS, coverage_types=COVERAGE_TYPES, subjects=SUBJECTS,
                      sources=BY_ID.values())


@pytest.mark.parametrize(("query", "terms", "filters"), [
    ("ransomware advisories from European publishers this week", "ransomware",
     {"hours": 168, "region": "EU", "coverage": "advisory", "sort": "relevance"}),
    ("security news today", "", {"hours": 24, "topic": "security", "sort": "latest"}),
    ("kubernetes release notes past month", "kubernetes", {"hours": 720, "coverage": "release", "sort": "relevance"}),
    ("latest openai news from TechCrunch", "openai", {"publisher": "techcrunch", "sort": "latest"}),
    ("chips news from Indian media", "", {"region": "APAC", "topic": "chips", "sort": "latest"}),
])
def test_natural_language_search_is_interpreted(query, terms, filters):
    reading = interpret(query)
    assert (reading["terms"], reading["filters"]) == (terms, filters)


@pytest.mark.parametrize("query", ["nvidia earnings", "AI regulation in Europe", "us election", "rust", ""])
def test_plain_keywords_are_not_reinterpreted(query):
    # Geography inside a story ("in Europe") is not a publisher region; topics need scope words.
    assert interpret(query) is None


def test_suggest_endpoint_returns_interpretation(store):
    client = TestClient(server.app)
    data = client.get("/api/search/suggest", params={"q": "ransomware advisories this week"}).json()
    assert data["interpretation"]["filters"]["coverage"] == "advisory"
    assert data["interpretation"]["summary"].startswith("“ransomware”")
    assert client.get("/api/search/suggest", params={"q": "ransomware"}).json()["interpretation"] is None
