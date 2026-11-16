# Informa AI

[Open Informa AI](https://ai-news-to-email-generator.vercel.app/)

Browse global technology news, research, security advisories, developer articles, and official release notes. Sources include TechCrunch, The Verge, Ars Technica, WIRED, engineering blogs, selected Medium feeds, and public Hashnode, DEV Community and Hacker News APIs. Search headlines, excerpts, authors, and tags. Filter by topic, subject, publisher, region, language, source type, and time.

Open a story in the Reading Room to read its supplied excerpt, find related coverage, or create a brief with links to the sources. Save articles, share a story link, or keep a named view of your filters in this browser. In **For You**, follow publications, topic feeds, and authors alongside your interests. The reader explains matches using shared headline terms or exact references such as CVE identifiers.

Preview the Global Top 5 or tailor a brief by coverage and reader perspective. Pin articles to include them and export the result as Markdown, HTML, or an email file. Briefs identify whether each summary comes from a publisher excerpt, a headline, or AI synthesis. Verified inboxes can receive a brief or opt in to the scheduled Global Top 5 when email delivery is configured.

The reader labels excerpts, headline-only records, and full articles shared with reviewed permission. Authors can verify their inbox and submit text and permission evidence for an already listed article in the [author workspace](https://ai-news-to-email-generator.vercel.app/contribute.html). Only the owner can approve publication. Authors can withdraw permission; the owner can revoke it. Submissions and verified email addresses stay private during review.

Hashnode discovery uses its free public feed endpoint, with bounded pagination and validation of dates and technology relevance. Publication-specific and individual-post API queries remain Pro-gated and are not used. Medium content comes from reviewed RSS feeds. No paywall bypass or automatic full-article extraction is performed. Coverage is limited to integrated sources and available history. Saved stories and followed lists stay on the originating browser.

## Run locally

Use Python 3.12 or later and Node.js 24.15 or later in the 24.x LTS line for frontend tests.

```sh
uv sync --frozen
npm ci
uv run uvicorn app.server:app --reload
```

The Reading Room and Global Top 5 work with public feeds. Set `NEWS_DATABASE_URL=sqlite:///./informa.db` for a local archive. See [.env.example](.env.example) for AI and delivery settings.

```sh
npm run lint
npm run build
npm test
uv run ruff check app tests scripts main.py
uv run pytest -q
```

Check live integrations without generating AI responses, sending email, or changing the archive:

```sh
uv run python -m scripts.check_sources
uv run python -m scripts.check_sources --source dev-community --source dev-latest --source hacker-news
```

[Competitive review](docs/PRODUCT.md) · [Deployment and configuration](docs/LAUNCH.md) · [HTTP API](docs/API.md)
