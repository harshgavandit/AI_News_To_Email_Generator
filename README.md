# AI Brief — AI News to Email Generator

A live AI reading room and personalized email digest by Harsh Gavand. Browse source-linked stories from OpenAI, Anthropic, and Matthew Berman's YouTube channel; generate a brief using OpenAI; then preview, copy, download, or send it to the owner's Gmail inbox.

**Live app:** https://ai-news-to-email-generator.vercel.app

## What the application does

- Collects five RSS feeds concurrently, deduplicates links, and caches feed responses for five minutes.
- Filters stories by source, title/excerpt search, and a 24-hour, 7-day, or 30-day window.
- Selects up to five recent stories across the chosen sources. The existing digest agent summarizes each feed excerpt, the curator ranks the summaries against your interests, and the email agent writes an introduction.
- Validates OpenAI output against Pydantic schemas and rejects rankings with invented IDs or duplicate positions.
- Renders a responsive email preview with original source links, relevance scores, and ranking explanations.
- Sends through Gmail only after owner authentication. The recipient is the configured owner inbox; public visitors cannot choose recipients. A signed, expiring preview prevents altered email payloads.

Summaries use **RSS titles and excerpts**, not full article text or YouTube transcripts. Anthropic feeds are maintained by the third-party [Olshansk/rss-feeds](https://github.com/Olshansk/rss-feeds) project and link to Anthropic originals. Feed failures appear in the interface; the app never substitutes fabricated news.

## Architecture

```text
Browser (HTML / CSS / JavaScript)
  -> FastAPI on Vercel
     -> Concurrent RSS collection and normalization
     -> OpenAI digest agent -> curator agent -> email introduction
     -> Signed email preview -> authenticated Gmail SMTP delivery
```

The deployed web flow is stateless and needs no database. The original batch pipeline remains available through `main.py`, using SQLite locally by default or MySQL through `DATABASE_URL` / existing `MYSQL_*` settings. Local SQLite is not used as durable storage on Vercel.

## Run locally

Requires Python 3.12+; Vercel uses Python 3.12 via `.python-version`. Install [uv](https://docs.astral.sh/uv/) and then:

```powershell
uv sync --frozen
Copy-Item .env.example .env
# Fill in real values in the saved .env. Never commit this file.
uv run uvicorn app.server:app --reload
```

Open http://127.0.0.1:8000. Interactive API docs are at `/api/docs`.

| Environment setting | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for real AI generation. Browsing feeds works without it. |
| `OPENAI_MODEL` | Model to use; defaults to `gpt-4o-mini`. |
| `MY_EMAIL` | Gmail sender and fixed destination for digest delivery. |
| `APP_PASSWORD` | Gmail app password, with Google two-step verification enabled. Spaces are removed before authentication. |
| `ADMIN_TOKEN` | Long random owner access key required by `/api/email`. Enter it only in the owner delivery dialog. |
| `DATABASE_URL` | Optional SQLAlchemy URL for the batch CLI. The deployed dashboard does not use it. |

Generate a random owner access key locally, save it as `ADMIN_TOKEN` in `.env`, and keep it private. API keys, Gmail settings, and the owner access key stay on the server. Do not place secrets in public JavaScript or screenshots.

### Original batch CLI

```powershell
uv run python main.py 24 10
```

This performs the original scraping, content/transcript enrichment, database persistence, digest generation, and Gmail delivery. Unlike the web preview flow, **this command sends email**. It is intended for a local machine or scheduled worker, not a long-running Vercel request. YouTube transcripts may be unavailable due to publisher restrictions or cloud IP blocking; the web flow uses feed excerpts instead.

## Deploy to Vercel

The repository is connected to the `ai-news-to-email-generator` project under `harshgavandits-projects`. Vercel detects `app/server.py` as FastAPI and serves `public/` assets through its CDN. `vercel.json` sets the request duration to 120 seconds.

```powershell
npx vercel link --project ai-news-to-email-generator --scope harshgavandits-projects
uv run python scripts/sync_vercel_env.py
npx vercel --prod --yes
```

The sync helper sends only the five application settings to the production environment through stdin. It does not print values or upload `VERCEL_OIDC_TOKEN`. Deploy again after changing production environment variables. Pushes to GitHub `main` also trigger the linked Vercel deployment.

## Verification

```powershell
uv run pytest -q
uv run ruff check app tests scripts main.py
node --check public/app.js
uv run python -m compileall -q app main.py
```

GitHub Actions runs the locked dependencies and offline checks on Python 3.12 and 3.14. Tests cover source filtering, unsafe feed links, input limits, caching, provider errors, ranking integrity, HTML escaping, authorization, signed-preview tampering/expiration, fixed-recipient delivery, and duplicate-send protection. They mock the provider and SMTP; live-provider results are recorded separately in [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Operational boundaries

- The dashboard is on demand. Deployment does not schedule a daily email or create subscriptions.
- The browser retains its current generated preview until reload. There is no hosted account system, archive, or subscriber database.
- Feed and digest caches, generation concurrency, request limits (three generations / two send attempts per ten minutes), and duplicate-send protection apply **per warm function instance**. They reset on cold starts and do not enforce an account-wide or distributed quota. Add a durable shared limiter and provider spending controls before high-volume public use.
- SMTP acceptance establishes that Gmail accepted the message for delivery; recipient inbox placement requires checking the mailbox.
- An available configuration flag in `/api/health` indicates settings are present. Real OpenAI and Gmail requests are needed to verify credentials.

## Codebase origins

The initial repository contains a tutorial-style batch aggregator and its original Git history. This deployment adapts that pipeline into a Vercel application, preserves the existing OpenAI migration, removes the heavyweight Docling/Torch dependency chain, and replaces the placeholder tutorial README and incompatible CI configuration with project-specific documentation and checks.
