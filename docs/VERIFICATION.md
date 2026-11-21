# Informa AI verification

## Persistent monitoring and research tools — November 17, 2026

- Release `07cc13e` passed Python 3.12 and 3.14 CI, including the isolated PostgreSQL job. Local regression checks passed 237 Python tests and 34 frontend tests. Optional PostgreSQL cases are skipped locally and run in CI.
- Production setup created the monitoring tables on PostgreSQL. An isolated session enrolled a watch, the worker checked it, a second session could not read it, stale revisions returned 409, and the session and test watch were deleted. A separate Chrome run verified consent, reload persistence, the 375px layout, Privacy-page deletion and an actual Markdown notes download containing source links.
- A production research query returned 12 evidence records through hybrid retrieval with the semantic index ready. A live article analysis returned a cited claim consistent with the supplied publisher excerpt and disclosed its limited source context. Verification found overly broad ranking for a two-term query, leading to a follow-up that boosts full query coverage and excludes weak semantic similarities.
- The public source briefing returned five source-linked records while the cached model edition was pending. Trend responses included equal-window publisher counts and rising-topic labels. Automated tests exercise grouping, duplicate alerts, retention, session isolation, conflicting edits and source eligibility.

## Global discovery and story summaries — November 17, 2026

- All 168 enabled integrations passed a live refresh into a disposable SQLite archive, including two valid feeds with zero eligible items. The refresh processed 5,550 source records in 49.18 seconds and retained 4,274 after deduplication and pruning. JetBrains Kotlin, JPCERT/CC Alerts, and arXiv Hardware Architecture returned 12, 6, and 16 eligible feed records respectively. Eighty-six retained article IDs occurred in two or more feeds.
- Live-fed API checks covered 90-day ranked search, separate cursor pages, Arabic publisher filtering, source-based recommendations, article summaries and provenance, trending topics, the Daily briefing, and a five-story digest with HTML and Markdown. Twenty-five repeated requests for one uncached Kotlin query through the local SQLite API measured a 44.3 ms p95. This measures a single local query and dataset.
- Chrome at 1440 and 375 CSS pixels checked the 90-day filter, article summary attribution, original-source links, saved-story persistence after navigation, and Arabic right-to-left reading. The Python suites exercise the archive upgrade and the approved, withdrawn, and revoked reading states against disposable SQLite and PostgreSQL databases. Browser client tests include permission-dependent summaries and removal of stale licensed content.
- Production promotion, production-scale load, and live AI and email delivery were outside this validation run.

## Workspace and daily briefing update — November 16, 2026

- The competitive review used public Particle, Trace and Feedly pages, published stylesheets, first-party documentation, and public product images. Computer Use stopped because it could not verify the browser URL on Windows. The redesigned desktop and mobile layouts therefore still need direct visual browser validation.
- Python 3.12 and 3.14 passed 215 tests each, including the disposable PostgreSQL archive cases. All eight client tests passed in jsdom. They exercise the actual Reading Room module, daily briefing navigation, source counts, read-state filtering, persistent monitoring views, modal pin selection, keyboard dismissal, focus isolation, licensed text, recommendations and author review.
- Ruff, Python compilation, JavaScript syntax, asset checks, and the static build passed. All nine linked stylesheets parsed in jsdom, producing 859 rules with zero stylesheet errors. This is a parsing check. Font files are served locally and their OFL license files are included.
- A live public-feed refresh into the disposable PostgreSQL archive reported all 165 integrations fresh. The corrected SCMP technology endpoint returned 34 eligible records. The briefing API selected five current stories from 654 sampled eligible records across 88 publishers. Reading details resolved for every selection, and the pinned selection generated a five-story global brief with HTML export.
- The live-fed archive check also exercised ranked search and non-overlapping cursor pages, and confirmed successful responses for the three HTML pages, new stylesheets, and self-hosted fonts through the FastAPI test client. Production publication, live OpenAI generation, and actual email delivery remain unverified in this pass.

## Coverage comparison and archive reliability — November 16, 2026

- The enabled integrations returned 5,518 source records from 165 public RSS and API endpoints in one audit. The seven added feeds returned 104 eligible records. A separate ingest into a disposable PostgreSQL archive retained 4,234 stories after canonical replacement and pruning. All 165 sources passed the archive readiness check.
- Live-fed local API checks covered ranked cursor pagination, Arabic publisher filtering, the journal filter, personalized recommendations, trending topics, and a two-source brief with HTML and Markdown exports. PostgreSQL used `brief_articles_search_trgm` on the observed `kubernetes` substring query. This measures one local query and dataset.
- Desktop browser checks opened related reporting on the Zoox launch, pinned three displayed reports into the brief composer, and reopened a saved article after a fresh navigation. At 375 CSS pixels, an Arabic article rendered right to left, the reader and page matched the viewport width, and the journal filter returned stories.
- Python 3.12 and 3.14 passed 208 tests each, including the disposable PostgreSQL cases. The six browser client tests, static asset build, and lint checks passed. Regression coverage includes false related matches, mismatched headline numbers, paused sources, shared retry state, and partial Hashnode rate limits. The validation used public feeds and a disposable archive. Live OpenAI synthesis, email delivery, and production promotion were outside this check.

## Regional discovery and feed synchronization — November 16, 2026

- The public source audit parsed 5,421 records from all 158 reviewed integrations in 27.99 seconds before archive deduplication and date filtering. The five added feeds were entARABI Arabic, TechNews Taiwan Semiconductors, Xataka España, Numerama, and the CNCF blog. Counts measure a single audit, and availability and publication recency can change independently.
- Discovery tests cover scoped For You matching in archive and direct-feed modes, including Arabic keyword search, language, region, subject, date, and malformed filters. The browser client test checks that changing a search in For You updates its request and shareable URL.
- Refresh tests cover persisted RSS validators, same-host redirects, `304` reuse, upstream failure, and targeted full recovery. Live repeat requests returned `304` from entARABI, TechNews Taiwan, Numerama, and PostgreSQL News. The PostgreSQL CI job checks the additive validator table and archive retention. No AI or email provider calls are required for these tests.

## Public community discovery and reading permissions — November 16, 2026

- The initial 136-source audit parsed 4,790 per-source records before archive deduplication and date filtering. A subsequent production connector check parsed 15 current Hashnode articles and ten records from each added Medium publication (ProAndroidDev, Level Up Coding and Towards AI). These counts change as sources update.
- Permission lifecycle tests exercise mailbox isolation, owner approval, evidence and review history, sanitization, grant replacement and withdrawal. The client tests cover article access labels, follow preferences, private submissions and editorial review. The tests use test records and transport doubles. No live article text was submitted or licensed as part of verification.
- The initial release `6429c34` passed the [GitHub Actions matrix](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/43878207499) on Python 3.12 and 3.14, including the isolated PostgreSQL job. The author workspace and 136 fresh sources were confirmed on the initial Vercel production deployment. The follow-up validation adds the three new Medium publications and the author session checks.

## Global technology discovery — November 16, 2026

- Local Python 3.14 regression run: **154 passed, 1 skipped**. The skipped case requires a disposable PostgreSQL service; the existing CI job runs that archive-upgrade test against PostgreSQL. New coverage exercises official API parsing, partial failures, deadline recovery, reviewed RSS fallbacks, author search, subject-filtered pagination and briefs, article details, recommendations, canonical duplicates, metadata sanitization, unsafe destinations and archive backfills. AI and mail provider calls remain mocked in these automated tests.
- Ruff, Python compilation, frontend JavaScript syntax checks and the production static build passed. The build now checks literal element references in the two frontend entry scripts against their HTML pages.
- The final concurrent live source audit checked **130 integrations**, all returning valid parsed records or a valid empty feed. It parsed **4,727 article records** in **24.5 seconds**. These are per-source records before canonical deduplication, publication-window filtering and archival retention. Source health and counts change over time; a valid feed does not guarantee recent publication.
- DEV's public API returned both editorial and latest article records. The official Hacker News API returned 40 completed stories during the concurrent audit. A standalone check returned 72; the bounded collector now preserves completed records when its deadline expires. Official RSS fallbacks remain subject to provider availability.
- Medium public RSS feeds and the selected Hashnode publication RSS were parsed. This earlier release tested Hashnode's legacy GraphQL endpoint, which redirects to its paid-access announcement. The later release uses a separate endpoint for the public discovery feed. No paid integration was provisioned.
- Computer Use stopped before visual testing because it could not determine the browser URL with sufficient confidence. No desktop/mobile screenshots or live browser interaction tests are claimed for this release. Source wiring, API integration journeys, asset build and live source checks provide separate verification.
- Run `uv run python -m scripts.check_sources` to repeat the public-source audit. Production release checks should additionally verify setup, fresh archive ingestion, reading details, interest ranking, subject filtering and global brief generation at the deployment URL. AI generation and actual email delivery require separate provider checks.

Production verification for application release `5ad1855`:

- GitHub Actions [43867267277](https://github.com/harshgavandit/AI_News_To_Email_Generator/actions/runs/43867267277) passed Python 3.12 and 3.14 (154 tests each), plus all 10 PostgreSQL archive tests. Its 10,000-recipient rehearsal used synthetic transport and observed zero duplicates; it sent no real email.
- Vercel deployment `dpl_YS3BWPqGTbpS87EYqZ6ohpjoGXta` reached Ready and was aliased to the production domain. The owner-authenticated archive setup returned `schema_ready: true` on PostgreSQL. Public JavaScript asset hashes matched the local release files.
- At 12:36 UTC on November 16, `/api/ready` returned 200 with all 130 enabled feeds fresh. Source checks are separate from publication recency; the selected Hashnode feed had no retained article within the archive window.
- Live API journeys verified 161 DEV articles in the seven-day window, author search, 228 cloud-subject matches, non-overlapping cursor pages, 12 personalized recommendations from 1,611 bounded candidates, five related stories, 10 observed trending topics, and a three-story cloud global brief with HTML and Markdown exports. Counts are time-dependent observations rather than product limits.
- Invalid recommendation preferences returned 422; unauthenticated owner setup returned 401. The live checks did not request paid AI synthesis, send email, or dispatch a workspace message. Browser interaction verification remains unavailable for the reason recorded above.

## Reading Room and digest update — November 15, 2026

- The locked environments passed 72 tests each on Python 3.12 and 3.14. The tests cover both news storage modes, sorted cursors, streamed previews, provider failure and fallback, size limits, verified-inbox delivery, and owner authorization. Ruff, Python compilation, frontend lint, and the static production build passed. Starlette emits a deprecation warning about its test client’s `httpx` integration.
- Chrome at 1440 and 375 CSS pixels exercised real RSS stories, pagination, date sorting, search and reset, saved stories across reload, multiple digest sources, the Global Top 5, preview controls, manual copying when clipboard permission was unavailable, and HTML and `.eml` export.
- The disposable PostgreSQL archive verified idempotent setup and ranked pagination. In the recorded ingest it reached 47 enabled feeds. An earlier run reached 44, reflecting feeds that can fail temporarily.
- A simulated transport processed 10,000 unique recipients in 100 batch calls with zero duplicates on both SQLite and PostgreSQL. This covers scheduling and fan-out with an isolated database and simulated provider.
- The updated production dependency lock had no known advisories in `pip-audit` at verification time.
- This update was verified locally. Personalized AI responses, SMTP and transactional email, and workspace delivery were exercised with test doubles. Live OpenAI generation, provider delivery, and Vercel promotion remain release checks.

## Historical deployment verification — October 21, 2026

Production URL: https://ai-news-to-email-generator.vercel.app

## Source and configuration analysis

The starting checkout was a Python batch application with no HTTP entry point or browser interface. It eagerly connected to a local MySQL server on import, did not declare the MySQL driver, imported Docling/Torch for HTML conversion, and had CI targeting Python 3.9–3.11 despite requiring Python 3.12+. Existing uncommitted OpenAI agent changes were preserved and completed.

The deployed application adds a FastAPI entry point, responsive dashboard, bounded RSS fetching, typed OpenAI responses, validated rankings, safe email rendering, and authenticated Gmail delivery. The CLI retains its separate persistence/enrichment flow with an optional local SQLite default. Environment settings are synced from the saved `.env` through stdin; secret values are never printed or included in source.

## Automated checks

- API/security tests pass, including a regression for Vercel serving `public/` through its CDN without bundling that directory in the Python function.
- Browser query-string windows 24/168/720 are tested explicitly.
- Ruff's syntax/undefined-name rules, Python compilation, and JavaScript syntax checks pass.
- Tests exercise real route behavior with mocked feed/provider/SMTP responses; these checks alone do not establish external integration success.
- GitHub Actions runs the locked environment on Python 3.12 and 3.14.

## Live production evidence

- `/`, static CSS/JavaScript/favicon assets, and `/api/health` respond successfully from the public production domain.
- All five feeds loaded: OpenAI News, Anthropic News/Research/Engineering, and Matthew Berman's YouTube channel.
- At verification time, the 24-hour, 7-day, and 30-day API windows returned 1, 20, and 104 matching stories respectively. Counts change as publishers update their feeds.
- A real production `/api/digest` request returned HTTP 200 with three source-linked articles, validated summaries, ranking scores/reasons, an introduction, Markdown, HTML, and an expiring signature.
- A separate browser submission rendered its three-story personalized preview successfully.
- An unauthenticated production email attempt returned HTTP 401.
- With the user's explicit authorization, exactly one test digest was submitted to `/api/email` using the owner access key. It returned HTTP 200 and `success: true`; Gmail SMTP accepted the message to the configured owner inbox. No mailbox was read to confirm inbox placement.
- The browser verified source filtering, search with no matches, generating a digest, copy/download controls, and the owner delivery dialog.
- Desktop and narrow mobile layouts were inspected. A decorative overflow discovered at the mobile breakpoint was corrected before the final release.

## Practical limits

The web summaries use RSS titles and excerpts rather than full articles/transcripts. Anthropic's RSS feeds are third-party maintained. The application runs on demand; no daily schedule or subscription list was created. Its caches, request limits, concurrency lock, and duplicate-send guard apply per warm function instance and are not a distributed quota. A successful send response proves SMTP acceptance, not delivery to the Inbox folder. No large-scale load test or separate production MySQL/CLI worker verification was performed.

The initial OpenAI key was rejected as expired. The replacement key passed a real request before being synced to production. Credentials visible in the user's setup screenshot should be rotated and re-synced; no secret values are recorded in this report.

## Design system layer and search scopes — November 21, 2026

- A clean Linux checkout (Node 22, Python 3.12, locked `uv sync`) passed `npm run lint`, `npm run build`, `npm test` (70 of 70), Ruff, `compileall`, `pytest -q` (357 passed, 37 PostgreSQL-only cases skipped) and `scripts.check_reader_quality`.
- The `reading.test.mjs` Saved-view case failed before these changes because start-up requests finished after the jsdom window closed; the test now lets them settle before teardown.
- A Chromium harness served `public/` with mocked story data and the real FastAPI `/api/search/suggest`. It exercised the Reading Room at 1440 and 390 CSS pixels in light and dark, card hover, the empty state, the story drawer, the Brief builder and Research Desk, Sources, About and Inbox, with no page errors. Typing "secu", pressing Down and Enter applied the Cybersecurity topic, cleared the query, restored newest-first sorting, updated the URL and showed the confirmation toast.
- Not covered: production data and deployment, live AI and email providers, Safari and Firefox, and screen-reader runs. On the Windows checkout `npm run build` needs Windows `node_modules`; run it there or in CI.
