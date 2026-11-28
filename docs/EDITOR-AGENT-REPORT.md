# Editor agent

The Editor agent reviews Informa’s stored archive and source checks. It drafts suggestions for the owner. The review graph has no tools for changing stories, pausing feeds, publishing notes, or creating Curiosity Cards. Those actions use the existing owner access key and a separate approval transaction.

## Build status

| Item | Implementation |
| --- | --- |
| 1. Review graph | LangGraph runs collect → detect → judge → explain → check → queue. Independent archive and source cursors advance with the queue transaction. Cheap detection precedes one batched judge call. The server verifies exact quotes against supplied records and constructs source links itself. Stable suggestion IDs retain rejection history. |
| 2. Scheduling | Archive and source review run at the end of the existing hourly intelligence job. The existing recap job drafts its note before building the completed week. Each graph has a 12 second processing budget, with no more than 18 candidates and a judge timeout of up to 7 seconds. Rows beyond the batch or candidate limit continue on a later run. Provider failures retain the affected cursor. |
| 3. Owner workspace | The queue filters by status, type, confidence, and age. Evidence, original links, and model or heuristic tags accompany each proposal. The owner can approve, edit and approve, reject, or snooze. Bulk approval is transactional and restricted to pending duplicates at or above 92% confidence. The paginated log keeps decisions, edits, and the receipts required for undo. |
| 4. Approved changes | Duplicate approval merges event memberships and timeline entries. Classification sets article topic, region, or language overrides. Hide excludes an article from archive reads and preserves the row. Source pauses use the shared source enable/disable operation. Recap approval exposes the note on its public week. Source review and Curiosity approval record a private acknowledgement or shortlist entry. |
| 5. Owner counts | The admin queue and existing owner feedback response show the pending count. The existing Curiosity upkeep report includes a count and review link. |
| 6. Evaluations | The 42-case synthetic suite scores six types, checked citations, rejection memory, and injected instructions. CI runs the stub. The existing manual live evaluation workflow offers an Editor option. |
| 7. Regressions | Tests cover archive cursors, a bounded candidate batch, guarded evidence, owner authentication, approvals and undo, details and timeline reads, and browser interaction. Database variants use the existing disposable PostgreSQL fixture. |

## Try it

1. Open `/admin-editor.html` on the local app or an approved preview. Enter the existing owner access key. The page holds it in memory until **Lock queue** or navigation.
2. Wait for the existing hourly intelligence job to review arrivals. The existing recap job can queue an Editor’s note for the last completed week.
3. Open a suggestion’s publisher links. Choose **Approve**, **Edit then approve**, **Reject**, or **Snooze 24 hours**. Select qualifying duplicates for bulk approval.
4. In **Activity log**, choose **Undo** on an approval to reverse it. If a later decision changed the same fields or event membership, undo the later decision first.

For a repeatable local replay, run `uv run --locked python -m scripts.run_evals --editor`. Tables initialize lazily using the repository’s PostgreSQL advisory lock pattern. The archive adds nullable override columns through its existing discovery schema initialization. Existing story metadata and publisher refreshes can coexist with those overrides.

## Stub evaluation

| Suggestion | Precision | Recall | Minimum for each |
| --- | ---: | ---: | ---: |
| Duplicate grouping | 100% | 100% | 80% |
| Misclassification | 100% | 100% | 80% |
| Hide | 100% | 100% | 80% |
| Source problem | 100% | 100% | 80% |
| Weekly recap | 100% | 100% | 80% |
| Curiosity candidate | 100% | 100% | 80% |

Citation accuracy, rejection memory, and injection resistance all met their 100% fixture thresholds. The hourly fixture reviewed **2 candidates in 1 batched judge call** and queued **2 suggestions**. The synthetic model measures pipeline behavior and evidence checking. The manual workflow measures provider behavior on the same corpus.

## Verification

| Check | Result |
| --- | --- |
| Python full suites | Python 3.12 on Windows and Python 3.14 on Linux each passed 706 tests with 92 skips. The feature’s PostgreSQL variants ran in the separate database check. |
| SQLite and PostgreSQL focus | 56 passed across Editor, recap, archive discovery, and Watch agent. A fresh PostgreSQL schema also initialized the editor tables without running the migration command. |
| Client and build | 162 client tests passed. JavaScript lint and the production asset build passed. |
| Chrome | The general release smoke passed. The owner flow at 390px verified anonymous access denial, edited approval, public article hiding, and undo against a disposable archive. |
| Policy and tooling | Ruff lint and format, Python compilation, type ratchet, and the Bandit gate passed. The local security and pipeline policy run passed 21 checks. |
| Offline evaluations | Ask Informa 40 cases, Deep Ask 25 cases, Watch agent 37 cases, and Editor agent 42 cases passed their thresholds. A local command correctly refused live Editor eval mode. |

## Boundaries and known gaps

- The hourly scan takes up to 80 new article rows and 120 source-health changes. A 30 second settling window keeps very recent writes eligible for a later scan. The first scan starts up to seven days back and needs an arrival timestamp.
- Candidate discovery is heuristic, so the agent can miss paraphrases, weak location signals, and quality problems that require reading beyond retained excerpts. Article language checks use stored public text. Source evidence uses a bounded history and a reviewed cadence signal. A quiet, normally infrequent publisher is not treated as a failed feed.
- A provider timeout leaves work available for retry. The configured daily call cap or shared AI budget causes conservative findings to be marked **Heuristic only**. Explanations and recap draft lines use checked publisher spans alongside fixed editorial framing.
- Hiding takes effect for current archive queries, detail pages, and subsequent builds. Browser caches, previously generated snapshots and already delivered material can continue to show their historical content. Approved recap notes can take up to a minute to appear in cached public recap responses.
- Undo preserves new reporting when reversing a grouping, and refuses to overwrite a later conflicting approval. The action restores archive and event state where possible. Earlier notification or email delivery cannot be recalled.
- Each type uses one stable identity per target and correction or issue. A rejection suppresses the same suggestion on subsequent scans. A recurring source issue of the same type is therefore visible through history rather than resurfacing as a new item.
- Curiosity approval keeps a private shortlist item. Source review records acknowledgement. Creating a Curiosity Card or editing a feed’s configuration uses the existing owner workflow.

## Environment variable names

`ADMIN_TOKEN`, `NEWS_DATABASE_URL`, `CRON_SECRET`, `FEED_REFRESH_SECRET`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `NEWS_AI_MODEL_FAST`, `NEWS_AI_RESEARCH`, `NEWS_AI_DAILY_BUDGET_USD`, `NEWS_AI_EDITOR_DAILY`.

## Files changed

- Editor graph, storage and authorization: `app/editor_agent.py`, `app/editor_store.py`, `app/editor_api.py`, `app/agent/openai_client.py`, `app/server.py`.
- Approved changes and reporting: `app/launch_store.py`, `app/coverage.py`, `app/discovery.py`, `app/event_intelligence.py`, `app/weekly_recap.py`, `app/feedback.py`, `scripts/curiosity_upkeep.py`.
- Workspace and recap UI: `public/admin-editor.html`, `public/admin-editor.css`, `public/admin-editor.js`, `public/recap.html`, `public/recap-page.js`, `vercel.json`.
- Evaluations and tests: `scripts/editor_evals.py`, `scripts/run_evals.py`, `evals/editor_cases.json`, `evals/editor_thresholds.json`, `tests/test_editor_agent.py`, `tests/test_security_controls.py`, `tests/client/admin-editor.test.mjs`, `.github/workflows/ci.yml`, `.github/workflows/ask-evals-live.yml`.
- Configuration and report: `.env.example`, `.gitignore`, `docs/EDITOR-AGENT-REPORT.md`.
