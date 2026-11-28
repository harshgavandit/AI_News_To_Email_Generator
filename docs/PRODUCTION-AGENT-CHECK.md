# Informa AI production agent check

Checked 28 November 2026 IST on [getinformdaily.com](https://getinformdaily.com/). Vercel reported the production alias as `READY` and `PROMOTED` on commit [`32b725bcaa7d3fb52296355e827e80b10ff94db8`](https://github.com/harshgavandit/AI_News_To_Email_Generator/commit/32b725bcaa7d3fb52296355e827e80b10ff94db8). GitHub `main` and the live health response reported the same revision. The [production release smoke](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46155792742) passed for health, home, Research Desk, the archive API, and RSS.

| Agent | Result | Production outcome |
| --- | --- | --- |
| Deep Ask | **Fail** | Streaming, both API formats, refusals, and cache worked. Neither answerable scenario produced a cited report. |
| Watch agent | **Partial** | Both drafts saved and the hourly job passed. The test inbox and the MCP preview had zero matches, so delivery and feedback remain unverified live. |
| Editor agent | **Partial** | The hourly run produced six source suggestions, and the weekly job drafted a private recap note. Owner authorization and evidence checks passed. The live eval missed four thresholds. |

## Readiness and boundaries

| Check | Result |
| --- | --- |
| `POST /api/admin/setup` | HTTP 200 on one owner-authenticated request. `schema_ready: true`, PostgreSQL, trigram search index. |
| `GET /api/health` | HTTP 200, `status: ok`, exact release SHA. |
| `GET /api/ready` | HTTP 200, `status: degraded`. 1,332 fresh sources, 36 failed, zero stale, zero pending, 1,368 enabled at the check. |
| `GET /api/news?hours=24&limit=30&catalog=0` | HTTP 200, 30 stories on the requested page. |
| Site health | [Manual run passed](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46156588420). |

The manual intelligence dispatch skipped publisher fetching and mail. The weekly recap used the existing job. The test used the owner setup endpoint, read the Editor queue, and created and removed a dedicated anonymous Watch profile. No Editor decisions, story or source mutations through admin controls, schedule changes, or test notifications to readers were performed.

## Deep Ask

Chrome exposed the Deep research mode and showed the planning state and the off-topic refusal. The production API emitted `plan`, `search`, `read`, `assess`, `write`, and `check` steps over SSE. The API supports repeated progress events for a second search round. The reported graph step count stayed within six and all API probes completed within the 45-second server limit.

| Scenario | Path | HTTP | Result | Steps | Stories read | Wall time |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| Open-weight model releases and reported capabilities in the past month | SSE | 200 | `insufficient` | 6 | 6 | 16.47 s |
| Cloud outages and AI regulation this month | SSE | 200 | `insufficient` | 6 | 0 | 6.78 s |
| Fictional foundry announcement in 2047 | JSON | 200 | `insufficient` | 6 | 0 | 5.72 s |
| Synthetic instruction override | SSE | 200 | `refused` | 0 | 0 | 0.27 s |
| Medical advice | Chrome | — | Scope refusal shown | — | — | — |
| Exact open-weight question after the rate-limit window | JSON | 200 | `insufficient`, `cached: true` | 6 | 6 | 0.51 s |

The first progress event for the open-weight question arrived at 0.52 s. The archive contained at least one directly relevant release, Ant Group's LingSante-3.1-flash, but both research probes returned zero sections, timeline entries, and citations. There was no answered result on which to validate clickable citations or sentence-level attribution. The production failure does not establish whether the loss occurred in evidence selection, assessment, or citation validation.

The five distinct Deep Ask questions, repeats, and two MCP calls are listed here. Quick Ask was exercised through its offline fixtures during this audit.

The MCP SDK connected to `/mcp` and called `deep_research` twice. The covered repeat returned `status: limited`, `reason: rate_limit` in 0.89 s. The synthetic override was refused in 0.20 s. Chrome showed the same temporary limit on the early repeat. The later JSON replay proved the cache hit and left the model counters unchanged.

```json
{"status":"insufficient","steps_used":6,"stories_read":6,"cached":true,"citations":[]}
```

## Watch agent

Chrome showed the plain-language Watch agent form under Research Desk → Topic alerts. The live save and cleanup used a dedicated cookie jar through the same API as the page. The cloud-provider outage draft took 3.02 s and required evidence of a provider outage. The open-weight draft took 2.39 s and required both a new release and an open-weight model. Both returned HTTP 200 `ready`. A synthetic attempt to override the watch guard returned HTTP 200 `refused` in 0.27 s before model drafting. Profile creation returned HTTP 201 with two watches.

The [manual intelligence run](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46156452004) completed in 54 s for the intelligence step. It reported `checked`, indexing `96`, `brief_status: answered`, no AI issue, and `push_sent: 0`. The legacy `watches_checked` and `alerts_created` counters were both zero. The workflow dropped the specific Watch and Editor metrics from the response it logged, so those job-level counts cannot be recovered from that run's output. No comparable pre-agent intelligence step runtime was available in the inspected workflow history.

The isolated inbox returned HTTP 200 with zero alerts. This leaves delivery, live deduplication, the Source-checked badge, and both feedback actions unverified. The MCP client listed four public examples in 0.72 s. `preview_watch` returned a structured open-weight draft in 6.98 s, `matching_status: ai`, and `matches: []`. The preview provided no positive match in this run, despite a relevant release elsewhere in the recent archive. The result does not identify whether the story reached the judge. Both pause calls returned HTTP 200. Removing the test watches returned HTTP 200 with zero watches. Removing the test profile returned HTTP 200, and a subsequent inbox read confirmed `active: false` and zero watches.

```json
{"status":"ready","matches":[],"matching_status":"ai"}
```

## Editor agent

- Chrome displayed the owner-key form with no queue visible. Without a key, `GET /api/admin/editor` returned HTTP 401. With the owner key, the queue returned HTTP 200 in 0.58 s with seven pending suggestions. The owner feedback endpoint returned the same count, seven, in 0.58 s.
- Six source suggestions arrived during the hourly run with confidence 0.82 and `mode: ai`. All six source links returned HTTP 200 and all six source IDs appeared in the public directory. The queue also held a recap suggestion at confidence 0.84. All ten citation excerpts matched their recorded titles or excerpts. Each of the recap suggestion's eight evidence records resolved in the archive and matched its stored publisher URL. One original link was opened in Chrome and displayed its publisher page. [Anthropic Research](https://www.anthropic.com/research/working-with-ai)
- The [weekly recap workflow](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46156585585) succeeded with `recap_status: partial` in 22.9 s for `2026-W47`. The owner queue contained a four-line draft with four citations and status `pending`. The same week's public recap returned HTTP 200 with zero editor-note lines. The queue contained zero `heuristic` items at the check. The offline Editor browser test passed with a `Heuristic only` item.

```json
{"week":"2026-W47","editor_note":null}
```

## Live fixture evaluations

The first Deep Ask, Watch, and Editor scoring attempts could not start because the Actions secret was missing. An earlier queued Watch dispatch was superseded under GitHub's single pending-run rule. After the secret was configured, the Deep Ask run attempted 19 planning calls and all 19 logged `BadRequestError`. The workflow supplied a blank `OPENAI_MODEL` when its optional variable was unset. Deep Ask scored five metrics below threshold. This was a model configuration failure, and the production question failures above occurred separately on the already configured production model. [Live Deep Ask run](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46157382796)

| Deep Ask metric (25 cases) | Score | Threshold |
| --- | ---: | ---: |
| Citation rate | 0 | 0.90 |
| Citation precision | 0 | 0.95 |
| Required fact recall | 0 | 0.80 |
| Timeline date accuracy | 0 | 0.95 |
| Follow-up success | 0 | 0.75 |
| Correct refusals | 1.0 | 1.0 |
| Correct insufficient results | 1.0 | 0.90 |
| Steps within limits | 1.0 | 1.0 |
| Prohibited-fact violations | 0 | 0 maximum |

The configured Deep Ask run used its one live run slot. Its artifact did not record usage totals. The 19 requests were provider rejects, and no completed model responses were recorded.

### Watch

The corrected Staging run completed all 37 fixture cases on `gpt-6-luna`. It recorded 31 drafts and 28 judging calls, with one failed draft and $0.011036 estimated spend. Successful model responses confirm the workflow credential works with the configured model. [Live Watch run](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46157903912)

| Metric | Score | Threshold |
| --- | ---: | ---: |
| Precision | 0.8400 | 0.92 |
| Recall | 0.7241 | 0.90 |
| Duplicate suppression | 0.8333 | 1.0 |
| Citation accuracy | 1.0 | 1.0 |
| Refusals | 1.0 | 1.0 |
| Feedback improvement | 0 | 1.0 |

Three outage cases included scheduled maintenance as an extra match. Several valid drafts were refused or unavailable. The duplicate metric requires one canonical outage per case, so an unavailable draft with no outage result also lowers this score. In the feedback tests, two runs already omitted the unwanted drill without feedback and one draft was refused. The zero score therefore records no measurable improvement under this fixture rule. These scores warrant a closer look at drafting and matching on frozen evidence before changing production behavior.

### Editor

The corrected Staging run completed all 42 cases on `gpt-6-luna`. It recorded 22 judging calls, zero provider failures, and $0.004326 estimated spend. [Live Editor run](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46158418046)

| Suggestion type | Precision | Recall | Threshold for each |
| --- | ---: | ---: | ---: |
| Duplicate | **0.7500** | 1.0 | 0.80 |
| Labels | 1.0 | **0.6667** | 0.80 |
| Hide | 1.0 | **0.3333** | 0.80 |
| Source | 1.0 | **0.7500** | 0.80 |
| Recap | 1.0 | 1.0 | 0.80 |
| Curiosity | 1.0 | 1.0 | 0.80 |

Citation accuracy, repeated-suggestion suppression, and injection resistance all scored 1.0 against 1.0 thresholds. The model accepted one false duplicate pair of similar cloud reports. The missed suggestions were a Japan region correction, a spam item, a future-dated story, and a persistent source failure. None of these fixture outcomes applied any changes to production. The model results identify classification errors, with no provider failure or demonstrated production code defect in those cases.

## Production load and estimated cost

The owner usage endpoint showed 30 calls and $0.009880 before testing, and 48 calls and $0.013767 after the cache replay. It reported zero provider failures in both snapshots and no configured daily USD ceiling. No daily cap or spend ceiling was reached in the production probes. The short-term Deep Ask request limiter fired as recorded above. These are shared production counters, so a background call in the same window may appear in a delta. GitHub fixture usage is separate.

| Production usage category | Additional calls | Estimated USD |
| --- | ---: | ---: |
| Deep Ask plan, assess, and write | 9 | 0.001469 |
| Watch draft and judge, including the public MCP preview | 4 | 0.000686 |
| Editor judging, including the recap window | 2 | 0.000835 |
| Other recorded work, including embeddings, digest, and brief | 3 | 0.000897 |
| Total | 18 | 0.003887 |

The successful model calls in the two recorded GitHub fixture runs cost an estimated $0.015362 combined. The Deep Ask provider rejects are excluded because that run lacked usage totals.

## Fixes and offline verification

| Confirmed issue | Staging fix |
| --- | --- |
| The intelligence and recap workflows discarded the agents' existing status and counter fields when displaying their API results. | `81584d0` retains only the safe metrics in those logs and tests both projections. |
| An unset workflow variable produced an empty model name. Live fixtures also omitted available usage counters from results. | `5df98ec` defaults blank values to the configured application default, tests all four relevant bounded routes, and records fixture usage in live artifacts. |
| The Editor browser unit test could not strip an import line on Windows CRLF checkouts. | `26c38d9` handles both line endings. |

- The full final Python suite passed **804 tests with zero skips**, including PostgreSQL variants on a fresh disposable pgvector instance. Expanded Editor coverage verifies that an existing recap draft prevents another model call, and a shared spend cap produces a heuristic suggestion without applying a story change. Both cases ran on SQLite and PostgreSQL.
- Final branch-inclusive coverage was **82.94%** against the 79% gate. Deep Ask was 88.76%, Watch agent 89.53%, Watch storage 90.35%, Editor agent 70.95%, and Editor API 85.13%. The [production revision's CI coverage](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/46155215934/job/141010304809) was 82.36% overall. The final run included the PostgreSQL cases, so the two percentages use different test environments.
- All 162 frontend tests passed after the CRLF fix. The production asset build, frontend and Python lint, and the type ratchet passed. The targeted Python rerun on the final fixes passed all 43 cases, including the workflow and Site health policy checks.
- All offline suites passed their existing thresholds. Quick Ask ran 40 cases, Deep Ask 25, Watch 37, and Editor 42. The two reader-intelligence quality replays passed. Live agent quality is assessed separately using the results above.

## Follow-up

- Add the live open-weight and two-angle queries as frozen evidence cases after identifying which stage lost relevant coverage. Keep the existing citation rules in place until those cases can distinguish missing evidence from useful abstention. Verify one successful cited answer and its story links on a later authorized live pass.
- Reproduce the MCP Watch preview miss with the stored release and the candidate shortlist. Verify delivery, duplicate suppression, source links, and feedback on a new isolated watch when a matching story naturally arrives.
- Replay the five Editor eval misses with their evidence and model decisions before changing the judging rules. The audit did not take a decision on any production item.
- Leave these fixes and this report on `Staging`. Production was checked on `32b725b`.
