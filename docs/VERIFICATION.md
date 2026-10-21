# Deployment verification — October 21, 2026

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
