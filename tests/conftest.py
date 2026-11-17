"""Routine checks use fixtures and disposable local services."""
import httpx
import pytest
import requests


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    environment = pytest.MonkeyPatch()
    config.add_cleanup(environment.undo)
    environment.setenv("PYTHON_DOTENV_DISABLED", "1")
    for key in ("NEWS_DATABASE_URL", "UPSTASH_REDIS_REST_URL", "OPENAI_API_KEY"):
        environment.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def block_live_http(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("Live HTTP is disabled in tests. Use a mock or an in-process transport.")

    async def reject_async(*args, **kwargs):
        reject()

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_async)
    monkeypatch.setattr(requests.sessions.Session, "send", reject)
