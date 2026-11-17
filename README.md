# Informa AI

[Open Informa AI](https://ai-news-to-email-generator.vercel.app/)

Browse global technology news, research, security advisories, developer articles, and official release notes. Sources include TechCrunch, The Verge, Ars Technica, WIRED, engineering blogs, selected Medium feeds, and public Hashnode, DEV Community and Hacker News APIs. Search headlines, excerpts, authors, and tags across up to 90 days of retained stories. Filter by topic, subject, publisher, region, language, source type, and time.

Use the Daily briefing for a five-story catch-up, or explore all stories, topics and saved monitoring views from the workspace navigation. Hide read stories from the loaded selection, compare supporting coverage, and pin a selection into the brief builder. The interface supports light and dark themes, card and list reading, and a compact mobile navigation.

Open the [Research Desk](https://ai-news-to-email-generator.vercel.app/research.html) to search publisher evidence, compare coverage, request cited analysis, and download research notes with source links. Opt in to background monitoring for up to six queries and review the private inbox when you return. The inbox updates after the archive and monitoring checks run. Delete watches and alerts under Privacy &amp; controls.

Open a story in the Reading Room to see its publisher excerpt and related reporting. When enough text is available, the story summary highlights sentences from the excerpt or an article shared with permission. Save articles, share a story link, pin reports to a brief, or keep a named view of your filters in this browser. In **For You**, follow publications, topic feeds, and authors alongside your interests. Search and filters narrow the articles before personalization ranks them. Coverage and related links show what connected the records, such as closely matching headlines or a shared CVE identifier.

Preview the Global Top 5 or tailor a brief by coverage and reader perspective. Pin articles to include them and export the result as Markdown, HTML, or an email file. Briefs identify whether each summary comes from a publisher excerpt, a headline, or AI synthesis. Verified inboxes can receive a brief or opt in to the scheduled Global Top 5 when email delivery is configured.

The reader labels excerpts, headline-only records, and full articles shared with reviewed permission. Authors can verify their inbox and submit text and permission evidence for an already listed article in the [author workspace](https://ai-news-to-email-generator.vercel.app/contribute.html). Only the owner can approve publication. Authors can withdraw permission; the owner can revoke it. Submissions and verified email addresses stay private during review.

Hashnode discovery uses its free public feed endpoint, with bounded pagination and validation of dates and technology relevance. Publication-specific and individual-post API queries remain Pro-gated and are not used. Medium content comes from reviewed RSS feeds. No paywall bypass or automatic full-article extraction is performed. Coverage is limited to integrated sources and available history. Saved stories and followed lists stay on the originating browser.

Meet the creator on [About](https://ai-news-to-email-generator.vercel.app/about.html), review [source standards](https://ai-news-to-email-generator.vercel.app/trust.html), and manage browser-stored reading data in [Privacy & controls](https://ai-news-to-email-generator.vercel.app/privacy.html). Export your browser data or selectively clear saved stories, read history, interests, and monitoring views. Optional audience analytics is off by default and respects Global Privacy Control and Do Not Track signals.

## Run locally

Use Python 3.12 or later and Node.js 24.15 or later in the 24.x LTS line for frontend tests.

```sh
uv sync --frozen
npm ci
uv run uvicorn app.server:app --reload
```

The Reading Room and Global Top 5 read the configured archive. Set `NEWS_DATABASE_URL=sqlite:///./informa.db` for an isolated local archive. Use the test fixtures for routine checks. See [.env.example](.env.example) for AI and delivery settings.

```sh
npm run lint
npm run build
npm test
uv run ruff check app tests scripts main.py
uv run pytest -q
```

Run live integration checks only for a deliberate source diagnosis. These commands contact publishers. For a specific issue, select only the affected sources:

```sh
uv run python -m scripts.check_sources
uv run python -m scripts.check_sources --source dev-community --source dev-latest --source hacker-news
```

[Competitive review](docs/PRODUCT.md) · [Deployment and configuration](docs/LAUNCH.md) · [HTTP API](docs/API.md)
