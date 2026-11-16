# Informa AI

**Your Personal AI News Intelligence Agent.**

Discover what matters. Understand why it matters. Stay ahead without information overload.

**Discover · Analyze · Personalize · Automate**

[Open Informa AI](https://ai-news-to-email-generator.vercel.app/)

Browse technology news, research, security advisories, and tutorials from publishers around the world, including Medium, DEV Community, and freeCodeCamp. Search and filter by topic, publisher, region, language, and time. Open a story to read its available excerpt and follow the link to the full article. Save articles or keep a named view of your filters in this browser.

Preview the Global Top 5 or tailor a brief by coverage and reader perspective. Pin articles to include them and export the result as Markdown, HTML, or an email file. Briefs identify whether each summary comes from a publisher excerpt, a headline, or AI synthesis. Verified inboxes can receive a brief or opt in to the scheduled Global Top 5 when email delivery is configured.

## Run locally

Use Python 3.12 or later and Node.js 20 or later.

```sh
uv sync --frozen
uv run uvicorn app.server:app --reload
```

The Reading Room and Global Top 5 work with public feeds. Set `NEWS_DATABASE_URL=sqlite:///./informa.db` for a local archive. See [.env.example](.env.example) for AI and delivery settings.

```sh
npm run lint
npm run build
uv run ruff check app tests scripts main.py
uv run pytest -q
```

[Competitive review](docs/PRODUCT.md) · [Deployment and configuration](docs/LAUNCH.md) · [HTTP API](docs/API.md)
