"""Routine checks use fixtures and disposable local services."""
import os
from uuid import uuid4

import httpx
import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


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


@pytest.fixture(params=["sqlite", "postgresql"])
def research_database(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'research.db'}"
        return
    url = os.getenv("TEST_NEWS_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_NEWS_POSTGRES_URL to a disposable PostgreSQL service")
    schema = f"test_research_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
    try:
        yield make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    finally:
        with admin.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
        admin.dispose()
