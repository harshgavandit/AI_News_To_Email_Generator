# Informa AI verification

## Global technology discovery — November 16, 2026

- Local Python 3.14 regression run: **154 passed, 1 skipped**. The skipped case requires a disposable PostgreSQL service; the existing CI job runs that archive-upgrade test against PostgreSQL. New coverage exercises official API parsing, partial failures, deadline recovery, reviewed RSS fallbacks, author search, subject-filtered pagination and briefs, article details, recommendations, canonical duplicates, metadata sanitization, unsafe destinations and archive backfills. AI and mail provider calls remain mocked in these automated tests.
- Ruff, Python compilation, frontend JavaScript syntax checks and the production static build passed. The build now checks literal element references in the two frontend entry scripts against their HTML pages.
- The final concurrent live source audit checked **130 integrations**, all returning valid parsed records or a valid empty feed. It parsed **4,727 article records** in **24.5 seconds**. These are per-source records before canonical deduplication, publication-window filtering and archival retention. Source health and counts change over time; a valid feed does not guarantee recent publication.
- DEV's public API returned both editorial and latest article records. The official Hacker News API returned 40 completed stories during the concurrent audit. A standalone check returned 72; the bounded collector now preserves completed records when its deadline expires. Official RSS fallbacks remain subject to provider availability.
- Medium public RSS feeds and the selected Hashnode publication RSS were parsed. Hashnode's current free GraphQL endpoint redirects to its paid-access announcement; no paid integration was provisioned and platform-wide Hashnode coverage is not claimed. No paywall bypass or complete article scraping was introduced.
- Computer Use stopped before visual testing because it could not determine the browser URL with sufficient confidence. No desktop/mobile screenshots or live browser interaction tests are claimed for this release. Source wiring, API integration journeys, asset build and live source checks provide separate verification.
- Run `uv run python -m scripts.check_sources` to repeat the public-source audit. Production release checks should additionally verify setup, fresh archive ingestion, reading details, interest ranking, subject filtering and global brief generation at the deployment URL. AI generation and actual email delivery require separate provider checks.

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
