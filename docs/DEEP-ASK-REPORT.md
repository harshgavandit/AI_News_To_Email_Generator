# Deep Ask implementation report

## Build status

| Item | Status | Result |
| --- | --- | --- |
| 1. Research graph | Done | Six LangGraph nodes, with one bounded follow-up search inside Assess. No checkpoint persistence. |
| 2. API | Done | JSON and SSE on `POST /api/ask/deep` with shared guardrails, admission, cache, and response deadline. |
| 3. MCP | Done | Read-only `deep_research` on `/mcp` calls the same service. The existing tools retain their interfaces. |
| 4. Frontend | Done | Quick and Deep modes on `/ask.html` and the homepage. Added progress, checked reports, a coverage timeline, numbered links and optional feedback. |
| 5. Evals | Done | 25 fixture cases with thresholds. Routine CI runs offline evaluations. Live Deep Ask evaluation is available in the existing manual workflow. |
| 6. Tests | Done | SQLite, disposable PostgreSQL, API and MCP integration, browser-facing tests, and release browser smoke. |
| 7. Docs | Done | Updated the API and MCP guides. Added the graph diagram, limits, use instructions, and this report. |

## Files and interfaces

- **Added backend** `app/archive_tools.py` and `app/deep_ask.py`. Updated `app/agent/openai_client.py`, `app/cache.py`, `app/feature_usage.py`, `app/feedback.py`, `app/launch_store.py`, `app/mcp_connector.py`, `app/research.py`, and `app/server.py`.
- **Updated web pages** `public/ask.html`, `public/ask.js`, `public/checked-answer.js`, `public/connect.html`, `public/index.html`, and `public/signature.css`.
- **Added fixtures and tests** `evals/deep_cases.json`, `evals/deep_thresholds.json`, `evals/fixtures/deep_archive.json`, `tests/test_deep_ask.py`, and `tests/client/deep-ask.test.mjs`. Updated `scripts/run_evals.py`, `scripts/check_release_browser.py`, and `tests/test_mcp_connector.py`.
- **Updated configuration and docs** `pyproject.toml`, `uv.lock`, `vercel.json`, `.gitignore`, both existing evaluation workflows, `docs/API.md`, and `docs/MCP.md`. Added `docs/DEEP-ASK.md` and this report.

The new endpoint is `POST /api/ask/deep` with JSON by default and SSE by content negotiation. The MCP interface is `deep_research(question, topic?, days?)`. Existing feedback and usage routes accept Deep Ask reports and consented counts.

## Verification

| Check | Result |
| --- | --- |
| `uv sync --frozen` and `uv lock --check` | Passed |
| `uv run python -m pytest -q` | 768 passed with SQLite and disposable local PostgreSQL 18. Separate SQLite-only run had 689 passes and 79 skips. |
| Archive-facing CI test selection | 190 passed with SQLite and disposable PostgreSQL 17 in Docker |
| Focused Ask tests on Python 3.14 Linux | Frozen install passed. 10 tests passed, 5 PostgreSQL variants skipped in this container. |
| `npm test` | 158 passed |
| `npm run lint` and `npm run build` | Passed |
| `uv run ruff check app tests scripts` and the type ratchet | Passed |
| Chromium release smoke | Passed at 390 and 320 px for Ask. The browser exercised the mode control, API availability state and narrow viewport. |
| `uv run python -m scripts.run_evals` | 40/40 synthetic cases passed |
| `uv run python -m scripts.run_evals --deep` | 25/25 synthetic cases met the thresholds |

The measured offline Deep Ask run took **1,329 ms** including fixture setup. Eight answered cases used one search pass and eight used two. All 16 answered cases and three insufficient cases used six graph steps. The six refused cases ran no graph steps. Citation rate, citation precision, required-fact recall, date accuracy and limit compliance were 100% on these fixtures. There were zero prohibited-fact violations. This measures the fixed archive and stubbed model.

## Function size and operational limits

The locked Python 3.12 Linux-compatible runtime installed into a temporary directory measured **117.3 MiB**, including **36.6 MiB** of files from newly added distributions. Counting the full `app/` and `public/` trees as well gives about **120.8 MiB**, before the Vercel wrapper. This is a local estimate below the documented **500 MB** Python limit. Real hosted bundle size was not measured. The Vercel function excludes eval fixtures, tests, virtual environments and temporary files. LangGraph installs its required transitive dependencies, including `langchain-core`. The application calls its existing provider gateway and disables graph tracing. [Vercel function limits](https://vercel.com/docs/functions/limitations)

The report uses retained publisher excerpts and publication dates. A warm worker caches for six hours. Separate workers can repeat a request within the shared database-backed quotas. After a timeout or disconnect, an in-flight synchronous database or provider operation may finish, but the agent starts no further searches or model calls after it sees the stop signal. Live-provider quality and hosted behavior remain unmeasured.

## Try it locally

```powershell
uv sync --frozen
npm ci
npm run build
uv run uvicorn app.server:app --host 127.0.0.1 --port 8000
```

Visit [http://127.0.0.1:8000/ask.html](http://127.0.0.1:8000/ask.html), choose **Deep research**, and ask about stories in a populated local archive. To verify the graph without credentials or live requests, run `uv run python -m scripts.run_evals --deep`.

Existing environment names for model-backed local use are `NEWS_DATABASE_URL` and `OPENAI_API_KEY`. Optional controls are `NEWS_AI_DEEP_DAILY`, `NEWS_AI_RESEARCH`, `NEWS_AI_DAILY_BUDGET_USD`, `NEWS_AI_MODEL_FAST`, and `NEWS_AI_MODEL_DEEP`. The added daily cap has a default.

No scheduled jobs were added or changed.
