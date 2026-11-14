# Informa AI

Browse recent technology news, research, service outages, and videos from publishers around the world. Search by keyword, sort by relevance or publication date, and filter by topic, region, format, publisher, or time. Share a filtered Reading Room link, save stories in your browser, or pin them for your next brief.

Get the Global Top 5 or build a brief around your interests, reader perspective, and pinned stories. Each story links to its source and indicates whether it uses an AI summary of the feed, a publisher excerpt, or a headline. Preview at full width or 375 pixels, switch the email preview to dark mode, and copy Markdown or download HTML or an email file.

Verify an inbox to send up to three briefs per UTC day. Readers can opt in to a daily global brief around 8 AM in their local timezone. Verified readers can also send a brief to a Slack or Microsoft Teams webhook.

[Open Informa AI](https://ai-news-to-email-generator.vercel.app/)

## Run locally

Use Python 3.12 or later and install the locked dependencies with `uv sync --frozen`. Start the app with `uv run uvicorn app.server:app`. The Reading Room and Global Top 5 can read public feeds directly. An optional local `NEWS_DATABASE_URL=sqlite:///./informa.db` enables the archive.

Run `uv run pytest -q`, `uv run ruff check app tests scripts main.py`, `npm run lint`, and `npm run build`.

[Deployment and configuration](docs/LAUNCH.md) · [HTTP API](docs/API.md)
