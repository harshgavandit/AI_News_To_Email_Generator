# Watch agent

Watch agent checks new stories in Informa’s archive against plain-language watches. Readers review the drafted conditions before saving. Alerts show an explanation, a publisher citation and controls for rating relevance. The feature uses the existing browser monitoring profile, Inbox, and opt-in Web Push subscription.

## Build status

| Item | Implementation and verification |
| --- | --- |
| 1. Watch creation | The Research Desk drafts an intent summary, topics, entities, search phrases, required and excluded conditions, and severity. The reader can edit and confirm them. The server validates edits and guards draft input. The six-watch limit is shared across all watch types. |
| 2. Matching graph | An in-memory LangGraph prefilters by topic, words, entity phrases, and a local character-trigram vector. A single judge call receives up to 10 stored stories. The graph attaches a checked source quote to the reviewed intent. The alert stores the archive’s original publisher link. Event IDs, the existing grouping heuristic and a durable event ledger suppress repeated coverage for a reader. |
| 3. Scheduling | The current hourly intelligence job runs the agent after the existing checks and event synchronization. It shares one archive batch of up to 420 recent arrivals across at most 16 due watches. A run evaluates at most 80 candidates and has a 24-second processing budget. Arrival cursors let unchecked watches continue on the next pass. |
| 4. Feedback | Good alert and Not relevant store a rating for that alert under the existing anonymous profile. The judge sees up to four recent negative examples for the same watch. Precision uses rated alerts as its denominator. |
| 5. Frontend | Research Desk supports creating, reviewing, editing, pausing, resuming and removing watches. Inbox and Research Desk show the reason, source, Source-checked badge, feedback and keyword fallback label. The Inbox offers device push using the existing permission prompt and delivery settings. |
| 6. MCP | `list_watch_examples` returns public examples. `preview_watch` drafts a watch and checks a bounded sample from the last 48 hours. Both use the public surface. Protocol tests check tool schemas and confirm those calls query neither private watches nor mail tables. |
| 7. Evals | 37 synthetic cases cover matches, near misses, exclusions, repeated coverage, unsafe inputs and negative feedback. CI runs the stub. The existing manual live evaluation workflow offers a Watch agent option. |
| 8. Tests | Backend tests exercise parsing, prefiltering, graph routing, budgets, unavailable-provider retries, arrival ordering, feedback, push deduplication and private profile isolation. Archive and delivery tests run on SQLite and PostgreSQL. Client tests exercise the preview-to-save flow, editing, source links and feedback. |

## Try it

1. Open **Research Desk → Topic alerts → Watch agent**.
2. Enter “Tell me when a major cloud provider has an outage.” Select **Review watch**, review the conditions, then select **Confirm and save**.
3. Open **Inbox → Watch alerts**. Optionally select **Enable Watch agent push**. New matching stories appear after the next eligible intelligence run. The watch starts at the time it is saved.
4. Open an alert’s publisher link and select **Good alert** or **Not relevant**. Return to the Research Desk to adjust or pause the watch. **Privacy & Control** can delete the monitoring profile, watches, and feedback.

For a repeatable local run using the bundled synthetic archive, use `uv run --locked python -m scripts.run_evals --watch`. Preview or production setup uses the existing owner database migration endpoint to add the tables and the arrival timestamp index. See [Launch guide](LAUNCH.md).

## Evaluation

| Metric | Stub result | Required minimum |
| --- | ---: | ---: |
| Precision | 100% | 92% |
| Recall | 100% | 90% |
| Duplicate suppression | 100% | 100% |
| Citation accuracy | 100% | 100% |
| Refusals | 100% | 100% |
| Feedback improvement | 100% | 100% |

The hourly fixture checked **4 watches**, evaluated **20 candidates**, attempted **4 batched judge calls**, and inserted **3 inbox alerts**. Explanations and citations used no extra calls. The stub measures pipeline behavior against curated fixtures. Real model relevance is evaluated separately by the manual workflow.

## Verification

| Check | Result |
| --- | --- |
| Python 3.12 full suite | 699 passed, 85 skipped on both Windows and Linux. Windows branch-inclusive coverage was 82.23% against a 79% gate. |
| Python 3.14 full suite | 699 passed, 85 skipped on Linux. CI selects the matrix Python version explicitly. |
| Final SQLite and PostgreSQL regression run | 116 passed across Watch agent, MCP, push, discovery, and syndication, using a disposable database. |
| JavaScript | 161 client tests passed. JavaScript lint and the production asset build passed. |
| Chrome | The release smoke passed. At 390px, the Watch agent worked through an unavailable draft, a stubbed draft, confirmation, real local save, fixture matching, the citation, and feedback. |
| Python checks | Ruff lint and new-file formatting, compilation, type ratchet, and the Bandit gate for high-severity, high-confidence findings passed. |
| Offline evaluations | Ask Informa 40 cases, Deep Ask 25 cases, and Watch agent 37 cases passed their thresholds. Both reader intelligence quality replays passed. |

## Cost, delivery and limits

- Drafting and judging use the existing fast model route and shared AI usage accounting. The daily judge call cap and overall cost ceiling switch matching to a conservative keyword fallback. Temporary provider failures keep the cursor in place and show a retry state.
- The arrival cursor is based on when a story is first stored. A short settling window allows ingestion to finish before the scan. Older rows that predate this migration have no arrival timestamp. The public MCP preview can still use their publication dates.
- A fit based on article excerpts can miss details behind a paywall or in links. Local vector similarities capture close word variants. Event deduplication depends on shared event IDs and overlap in stored coverage, so very different reporting can be grouped separately.
- The per-run limits defer busy queues. Several strong matches on a single archive page can compete for the ten candidate slots. Reports that arrive after the job’s settling window are eligible at the next run.
- Push shares existing quiet hours, spacing, and daily caps with other followed updates. One pending Watch agent alert per eligible device is considered in a dispatch. Inbox alerts are available independently of device permission or push acceptance. If the process stops after the push provider accepts a notification and before recording the receipt, the retry uses the same notification tag.
- The model receives the reviewed watch, a bounded set of public title and excerpt pairs, and any recent negative examples used for this watch. Ratings and the event ledger are scoped to the existing anonymous monitoring profile. Graph tracing is disabled for private watch data. The watch flow records no analytics events and uses the existing opt-in controls for site analytics.

## Environment variables

`OPENAI_API_KEY`, `OPENAI_MODEL`, `NEWS_AI_MODEL_FAST`, `NEWS_AI_RESEARCH`, `NEWS_AI_DAILY_BUDGET_USD`, `NEWS_AI_WATCH_JUDGE_DAILY`, `NEWS_AI_WATCH_AGENT_DRAFT_DAILY`, `NEWS_DATABASE_URL`, `NEWS_PUSH_VAPID_PRIVATE_KEY`, `NEWS_PUSH_SUBJECT`, `PUBLIC_ORIGIN`, `CRON_SECRET`.

## Files changed

- Matching, state and integration: `app/watch_agent.py`, `app/watch_storage.py`, `app/monitoring.py`, `app/launch_store.py`, `app/coverage.py`, `app/server.py`, `app/agent/openai_client.py`.
- Push and MCP: `app/push_alerts.py`, `app/push_api.py`, `app/mcp_connector.py`.
- Reader UI: `public/research.html`, `public/research.js`, `public/research.css`, `public/watch-agent-ui.js`, `public/inbox.html`, `public/reader-inbox.js`, `public/push-alerts.js`, `public/privacy.html`.
- Evals and CI: `scripts/run_evals.py`, `scripts/watch_evals.py`, `evals/watch_cases.json`, `evals/watch_thresholds.json`, `evals/fixtures/watch_archive.json`, `.github/workflows/ci.yml`, `.github/workflows/ask-evals-live.yml`.
- Regressions and documentation: `tests/test_watch_agent.py`, `tests/test_mcp_connector.py`, `tests/client/research.test.mjs`, `tests/client/reading.test.mjs`, `docs/MCP.md`, `docs/WATCH-AGENT-REPORT.md`, `.env.example`, `.gitignore`.
