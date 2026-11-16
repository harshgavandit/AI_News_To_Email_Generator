# Informa AI

**Your Personal AI News Intelligence Agent.**

Discover what matters. Understand why it matters. Stay ahead without information overload.

**Discover · Analyze · Personalize · Automate**

[Open Informa AI](https://ai-news-to-email-generator.vercel.app/)

Browse technology news, research, security advisories, and developer articles from publishers around the world. Coverage includes TechCrunch, The Verge, Ars Technica, WIRED, engineering blogs, selected Medium and Hashnode publication feeds, and official DEV Community and Hacker News APIs. Search headlines, excerpts, authors, and tags. Filter by topic, subject, publisher, region, language, and time.

Open a story inside the Reading Room to read its supplied excerpt, find related coverage, or create a source-linked AI brief. Original articles and Hacker News discussions remain one click away. Save articles, share a story link, or keep a named view of your filters in this browser. In **For You**, choose interests and followed sources for a diverse selection ranked across the recent archive.

Preview the Global Top 5 or tailor a brief by coverage and reader perspective. Pin articles to include them and export the result as Markdown, HTML, or an email file. Briefs identify whether each summary comes from a publisher excerpt, a headline, or AI synthesis. Verified inboxes can receive a brief or opt in to the scheduled Global Top 5 when email delivery is configured.

The reader displays short publisher-supplied excerpts. It does not extract full articles or bypass paywalls. Hashnode's GraphQL API requires a paid publication plan, so this app uses its selected public RSS feed. Coverage is limited to integrated sources and their available history. Saved stories and preferences stay on the originating browser; selected preferences are submitted to rank recommendations.

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

Check live integrations without generating AI responses, sending email, or changing the archive:

```sh
uv run python -m scripts.check_sources
uv run python -m scripts.check_sources --source dev-community --source dev-latest --source hacker-news
```

[Competitive review](docs/PRODUCT.md) · [Deployment and configuration](docs/LAUNCH.md) · [HTTP API](docs/API.md)
