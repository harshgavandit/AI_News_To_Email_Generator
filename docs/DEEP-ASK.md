# Deep Ask

Deep Ask researches broad technology questions against Informa’s retained archive. It returns a short summary, three to six sections, and a dated timeline. Numbered citations open the exact stories in the Reading Room. Timeline dates come from the cited stories’ publication timestamps.

```text
plan → search → read → assess ──enough──▶ write → check → END
         ▲                │
         └──── gaps ──────┘  at most one follow-up round (MAX_ROUNDS = 2)
```

- **Plan** turns the question into up to two keyword searches. **Search** uses the same archive search as MCP, with a single bounded SQL query per keyword search.
- **Read** deduplicates stories and keeps retained English publisher excerpts. It reads the excerpts already returned by search.
- **Assess** checks coverage. A conditional edge loops back to **Search** for one follow-up round when there are gaps and time, story and round limits allow; otherwise it goes to **Write**.
- **Write** groups relevant complete source sentences under editorial headings. **Check** validates every sentence and its source, checks quotes and links, and drops invalid sections and dates. An answer needs a checked summary, at least three distinct section claims across three sections, and at least one dated entry.

## Limits

| Control | Limit |
| --- | --- |
| LangGraph execution | Six nodes; Assess loops back to Search at most once (recursion limit 10) |
| Search | Two passes, four keyword queries, 25 excerpts read in total |
| Time | 45 seconds for the response, with per-call provider timeouts |
| Model | Up to four routed attempts. The 28,000-token allowance conservatively bounds serialized input, schema overhead, and output. Completion limits include reasoning tokens. |
| Per-IP calls | Three requests per ten minutes across the website and MCP |
| Daily calls | 20 uncached runs by default, configurable through `NEWS_AI_DEEP_DAILY`. Set it to zero to disable new runs. Model attempts also use the existing estimated spend limit. |
| Cache | Six hours in a warm worker, keyed by normalized question, topic, window, database scope and model routing. Repeated requests to another worker may run again. |

Search reaches only the stored archive. Model calls use existing provider routing, without retries or a fallback provider call. Graph state stays in memory. Research neither changes the ingestion schedule nor needs a database migration. Analytics uses the existing opt-in feature counts and respects Global Privacy Control and Do Not Track. A reader can choose to send an answer report with the question and source IDs.

## Try it locally

```powershell
uv sync --frozen
npm ci
npm run build
uv run uvicorn app.server:app --host 127.0.0.1 --port 8000
```

Open [Ask Informa locally](http://127.0.0.1:8000/ask.html), select **Deep research**, and ask about several related stories stored in your local archive. Point the app at an existing SQLite archive and configure the existing research model in the ignored local environment to get a model-generated answer.

The deterministic fixture evaluation works without a model key or a populated database.

```powershell
uv run python -m scripts.run_evals --deep
```

The [API reference](API.md) describes JSON and progress streaming. The [MCP guide](MCP.md) describes the `deep_research` tool.
