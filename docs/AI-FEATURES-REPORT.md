# Informa AI feature report

These features build on Staging revision `2ca8d27`. Production verification is pending a future release.

## 1. Guardrails — done

- **Files.** Added [app/guardrails.py](../app/guardrails.py), [public/checked-answer.js](../public/checked-answer.js), and Python and frontend regressions. Updated `app/insight_api.py`, `app/research.py`, `app/feedback.py`, `public/story-question.js`, `public/signature.css`, `public/privacy.html`, and [API.md](API.md).
- **Endpoints.** Story-scoped `POST /api/intelligence/converse` returns the checked result under `answer.guardrails`. `POST /api/feedback` accepts explicit `ai_answer` reports with a question and public story IDs. Reports go to the existing private feedback inbox.
- **Tests.** [Python tests](../tests/test_guardrails.py) cover rejected input, missing and invented citations, foreign links, invented quotations, real API rejection and acceptance, and storage of a report without a contact field. The [frontend test](../tests/client/checked-answer.test.mjs) verifies the badge, clickable citations, and report payload. Both passed.
- **Try it.** In the local [Reading Room](http://127.0.0.1:8000/#reading-room), open an archived story, select **Ask about this story**, and ask about a detail in the publisher excerpt. **Report this answer** appears on a checked answer. Run `uv run python -m pytest -q tests/test_guardrails.py` for a fixture-backed exercise.
- **Known limits.** The input checks use deterministic patterns and may refuse a legitimate question about prompt injection. An answered result uses complete source sentences. A short or incomplete excerpt may be insufficient for synthesis across sources. Other established AI workflows retain their existing validation.
- **Configuration.** Existing `NEWS_DATABASE_URL` and `OPENAI_API_KEY` enable real evidence and model responses. There is no separate guardrails setting.

## 2. Ask Informa — done

- **Files.** Added [app/ask.py](../app/ask.py), [public/ask.html](../public/ask.html), [public/ask.js](../public/ask.js), and API and frontend tests. Updated `app/server.py`, `app/research.py`, `app/story_groups.py`, `app/feature_usage.py`, `public/index.html`, `public/signature.css`, `public/privacy.html`, `vercel.json`, and [API.md](API.md).
- **Endpoints and pages.** `POST /api/ask` accepts a question with optional `topic` and `days`. The form is on the homepage and at `/ask.html`. Anonymous usage counts follow the existing consent, GPC and DNT rules.
- **Tests.** [Python tests](../tests/test_ask.py) verify stored-vector and keyword ranking, date scope, rejection of unsupported model text, checked and inconclusive cache hits, validation, unavailable behavior and rate limits. Five [frontend tests](../tests/client/ask.test.mjs) cover response states. Mobile Chrome opened the standalone page and exercised the real refusal and unavailable routes. All passed.
- **Try it.** Open [Ask Informa locally](http://127.0.0.1:8000/ask.html), choose a question that matches the retained archive, and select a time window. `uv run python -m pytest -q tests/test_ask.py` supplies its own archive and stub model.
- **Known limits.** Answers depend on the coverage and excerpts in the chosen 1–30 day window. Checked answers can be reused for 30 minutes before the question is searched again. An up-to-date semantic index improves recall. The local tests exercise both stored vectors and keyword fallback.
- **Configuration.** Existing `NEWS_DATABASE_URL` and `OPENAI_API_KEY` continue to apply. `NEWS_AI_RESEARCH` controls AI availability and `NEWS_AI_VECTORS` enables semantic retrieval. Existing limits include `NEWS_AI_DAILY_BUDGET_USD`, `NEWS_AI_ANSWERS_DAILY`, and `NEWS_AI_QUERIES_DAILY`. Optional `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` share the cache across instances.

## 3. Evals — done

- **Files.** Added [scripts/run_evals.py](../scripts/run_evals.py), [40 cases](../evals/ask_cases.json), [the synthetic archive](../evals/fixtures/ask_archive.json), [thresholds](../evals/thresholds.json), [the latest report](../evals/results/latest.json), [scoring tests](../tests/test_ask_evals.py), and [the manual live workflow](../.github/workflows/ask-evals-live.yml). Updated [Python checks](../.github/workflows/ci.yml), [API.md](API.md), and the Bash resolution in the existing pipeline-policy test for Windows.
- **Results.** The 40-case stub run passed with 100% citation rate, citation precision, required-fact recall, correct refusals, and status accuracy. There were zero prohibited-fact violations. Both scoring tests passed, including a deliberately bad result falling below thresholds.
- **Try it.** Run `uv run python -m scripts.run_evals`. For an intentional provider run, use `uv run python -m scripts.run_evals --live` or manually dispatch **Ask Informa live evaluation** in GitHub Actions after the workflow is published.
- **Known limits.** The stub tests retrieval and checks on fixtures. Provider reasoning, live archive coverage, and production costs require a live run. The paid live workflow was not executed.
- **Configuration.** Stub mode needs no environment variables. Live mode uses `OPENAI_API_KEY`, optionally `OPENAI_MODEL`, `NEWS_AI_MODEL_STANDARD`, and `NEWS_AI_DAILY_BUDGET_USD`.

## 4. MCP connector — done

- **Files.** Added [app/mcp_connector.py](../app/mcp_connector.py), [public/connect.html](../public/connect.html), [public/connect.js](../public/connect.js), [MCP.md](MCP.md), and [transport and contract tests](../tests/test_mcp_connector.py). Updated `app/server.py`, `app/curiosity.py`, `public/ask.html`, `vercel.json`, `pyproject.toml`, `uv.lock`, and the [Chrome smoke harness](../scripts/check_release_browser.py).
- **Endpoints and pages.** `/mcp` provides the official SDK's stateless Streamable HTTP transport with JSON responses. `/connect.html` explains Claude, ChatGPT and Cursor setup, with a copyable endpoint and Cursor configuration.
- **Tests.** All 15 tests passed on both SQLite and Docker PostgreSQL. The SDK client initialized, pinged, listed seven strict read-only tools, and called every tool without application startup lifespan. Tests covered malformed arguments, transport limits, the shared Ask limit, host/origin validation, and checked that tool execution touched no mail, subscriber, feedback, or research-project tables. Mobile Chrome verified the copy control.
- **Try it.** Start the local app using `uv run uvicorn app.server:app --host 127.0.0.1 --port 8000`. Open the [connection guide](http://127.0.0.1:8000/connect.html) or point a Streamable HTTP client at `http://127.0.0.1:8000/mcp`. Run `uv run python -m pytest -q tests/test_mcp_connector.py` for a fixture-backed round trip.
- **Known limits.** The deployed Vercel endpoint and individual hosted Claude, ChatGPT and Cursor connections still need a post-release smoke test. The connector serves JSON over Streamable HTTP. It does not provide a persistent SSE stream or browser cross-origin access. Read-only queries use the existing per-instance IP limiter. Ask uses the shared database-backed quota.
- **Configuration.** There are no MCP credentials. Public archive tools use existing `NEWS_DATABASE_URL`. `ask_informa` also uses the same AI configuration as `/api/ask`.

## Release checks

- `uv sync --frozen` and `uv lock --check` passed.
- The original `uv run python -m pytest -q` run finished with **679 passed and 48 skipped**. Skips included tests that require `TEST_NEWS_POSTGRES_URL`. An earlier run hit an SQLite lock in the existing feed-sweep test during parallel validation.
- Follow-up verification on the local Docker PostgreSQL 17 instance with pgvector 0.8.7 passed **179 feature and archive regression tests across SQLite and PostgreSQL**. The PostgreSQL regression verified native vector retrieval in an isolated schema. This exposed a search-path issue fixed in `app/vector_search.py` by qualifying pgvector's distance operator. Guardrails, Ask and MCP now run in the PostgreSQL CI job as well. Tests used a temporary database.
- `npm test` passed all **153 tests**. `npm run build`, `npm run lint`, and `uv run ruff check app tests scripts` passed.
- The existing type-error ratchet, reader quality replay, and Chrome release smoke passed.
- `uv run python -m scripts.run_evals` passed all **40 stub cases**.

The Vercel deployment policy, publisher schedule and existing crons match the base revision. No production keys, production database, or hosted deploy were used in verification.
