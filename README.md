# AI News to Email Generator

This app collects recent AI news from OpenAI, Anthropic, and Matthew Berman's YouTube channel and turns it into a personalized email digest.

You can browse stories, search by keyword, and filter by source or by the past 24 hours, 7 days, or 30 days. Enter the topics you care about and choose a three-story or five-story digest. The app uses OpenAI to summarize the available stories and rank them by relevance to your interests.

Each digest includes short summaries, links to the original sources, and an explanation of why each story was selected. You can read the preview, copy it, download it as an HTML email, or send it to the configured Gmail inbox using the owner's access key.

The summaries are based on the titles and excerpts available in the sources' RSS feeds.

[Open the app](https://ai-news-to-email-generator.vercel.app)

## How the web app works

```text
RSS feeds → validated source links + dated excerpts → source/time/search filters
  → select up to five stories across chosen sources
  → OpenAI summaries → personalized ranking → Markdown + escaped HTML preview
  → copy/download, or owner-authorized Gmail delivery
```

The selection step takes recent stories in source round-robin order; the model ranks that selected set. It does not evaluate every available article before choosing candidates.

| Code | Responsibility |
| --- | --- |
| [`app/news.py`](app/news.py) | Concurrent RSS collection, link validation, source availability, and a five-minute in-memory feed cache. |
| [`app/web_digest.py`](app/web_digest.py), [`app/agent/`](app/agent/) | Typed summaries, validated article IDs/rankings, personalized introduction, and email rendering. |
| [`app/server.py`](app/server.py) | FastAPI routes, input/origin checks, bounded generation, expiring preview signatures, and owner delivery authorization. |
| [`public/`](public/) | Browser interface, filters, digest preview, copy/download, and delivery dialog. |
| [`app/services/email.py`](app/services/email.py) | Gmail SMTP delivery to the configured owner inbox. |

## Run locally

Use Python 3.12 and Node.js for the optional JavaScript syntax check. From the repository root:

```powershell
python -m pip install uv
uv sync --frozen
Copy-Item .env.example .env
uv run python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
```

On macOS/Linux, copy the environment template with `cp .env.example .env`. Open <http://127.0.0.1:8000>. Set the following values in the untracked root `.env`, then restart the server:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for generating a digest; browsing feeds does not require it. |
| `OPENAI_MODEL` | Generation model; defaults to `gpt-4o-mini`. Use a model available to your provider project. |
| `MY_EMAIL` | Gmail sender and the web app's fixed recipient. |
| `APP_PASSWORD` | Gmail app password used by SMTP; required for delivery. |
| `ADMIN_TOKEN` | Owner access key for delivery and the secret used to sign generated previews. Set a long random value. |

The preview can be read, copied, or downloaded without sending email. Generating it makes real provider requests. Sending requires the owner key and a valid generated preview; the recipient is not supplied by the visitor. Keep credentials server-side.

API routes are `/api/news`, `/api/digest`, `/api/email`, and `/api/health`; interactive schemas are available at `/api/docs`. Health reports configuration flags without calling the model or testing SMTP.

## Tests and verification

```powershell
uv run python -m pytest -q
uv run ruff check app tests scripts main.py
uv run python -m compileall -q app main.py
node --check public/app.js
```

[`tests/test_web.py`](tests/test_web.py) covers filters/time windows, invalid inputs, cache/signature behavior, provider failures, unsafe feed links, invented ranking IDs, delivery authorization, changed/expired previews, and repeat-send rejection. Feed, provider, and SMTP responses are mocked; these checks do not send email or establish live provider availability. [GitHub Actions](.github/workflows/ci.yml) runs the locked environment on Python 3.12 and 3.14.

The [21 October deployment record](docs/VERIFICATION.md) describes the observed public API/browser checks and a separately authorized SMTP acceptance check. It is dated evidence, not a guarantee of current feed availability or inbox placement.

## Deployment and batch workflow

[`vercel.json`](vercel.json) deploys `app/server.py` as FastAPI and serves `public/` as static assets. The web path does not need a database. Set the same server-side environment variables on the deployment.

The original batch entry point, [`main.py`](main.py), separately runs scraping, article/transcript enrichment, stored digest generation, and email delivery. It uses [`app/profiles/user_profile.py`](app/profiles/user_profile.py) and [`app/database/`](app/database/). With its provider/Gmail settings configured, `uv run python main.py 24 10` processes a 24-hour window and attempts to send a digest of up to ten stories. This command sends email directly; it is not a preview command. Batch storage defaults to local `ai_news.db`; optional `DATABASE_URL` selects another SQLAlchemy database. This worker is not invoked by the hosted web app or scheduled by the repository.

## Limits

The web app summarizes RSS excerpts rather than full articles or video transcripts. Anthropic feeds are maintained by a third party, and publisher availability affects results. Feed/digest caches, request limits, the generation lock, and repeat-send history live in one process; they are not shared quotas or durable delivery records across Vercel instances. There is no subscriber list or automatic daily schedule. SMTP acceptance does not establish delivery to the Inbox folder, and the app has no durable mail queue.
