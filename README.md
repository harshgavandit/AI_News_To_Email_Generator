# Informa AI

Browse AI, startups, security, software and cloud, chips and hardware, tech companies, research, industry policy, and service outages. The Reading Room draws on 83 reviewed RSS and Atom feeds, including local publishers in Africa, Asia-Pacific, Europe, Latin America, the Middle East and North Africa, and North America. Filter by topic, publisher region, source type, format, and time. Search titles, publisher names, and excerpts in their original language, and share a link to the filtered view.

Get the Global Top 5 or build a brief around a topic, publisher region, reader perspective, and pinned stories. Each story links to its source and distinguishes independent reporting, official announcements, security advisories, preprints, and other source types. Briefs label AI summaries, publisher excerpts, and headline-only stories. Copy Markdown or download HTML or an email file.

Verify an inbox to send up to three briefs per UTC day. Readers can opt in to a daily global brief around 8 AM in their local timezone. Verified readers can also send a brief to a Slack or Microsoft Teams webhook.

[Open Informa AI](https://ai-news-to-email-generator.vercel.app/)

## Run locally

Use Python 3.12 or later and install the locked dependencies with `uv sync --frozen`. Start the app with `uv run uvicorn app.server:app`. The Reading Room and Global Top 5 can read public feeds directly. An optional local `NEWS_DATABASE_URL=sqlite:///./informa.db` enables the archive.

Run `uv run pytest -q`, `uv run ruff check app tests scripts main.py`, `npm run lint`, and `npm run build`.

[Deployment and configuration](docs/LAUNCH.md) · [HTTP API](docs/API.md)
