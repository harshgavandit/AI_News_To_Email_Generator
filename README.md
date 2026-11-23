# Informa AI

**Global technology news, without the noise.** Informa AI collects stories from 834 reviewed English-language sources. You read the headlines and short summaries, then follow the link to the publisher for the full story.

**[Open Informa AI →](https://getinformdaily.com/)**

---

## Why Informa

- **One place for tech news.** It covers news, research, engineering blogs, security advisories, release notes, newsletters and podcasts, from outlets such as TechCrunch, The Verge, Ars Technica and WIRED, plus Hacker News, DEV and Hashnode.
- **Every summary shows its source.** Each one says whether it came from a publisher excerpt, a headline or AI. AI answers cite the sources they used.
- **Built to save time.** A five-story daily brief, a "Catch up" view of what changed since your last visit, and a morning email that only includes news from what you follow.
- **Respects publishers and readers.** It doesn't bypass paywalls or copy full articles. Analytics is off by default, and your reading data stays in your browser.

## What you can do

| | |
|---|---|
| 📰 **Reading Room** | Search 90 days of stories by topic, publisher, region, language or source type. Save stories, hide ones you've read and compare coverage. |
| ⚡ **Catch up** | See what's new since your last visit, including confirmations, corrections and scope changes. Each development has its own timeline page. |
| ✉️ **Briefs** | Get the Global Top 5 or build your own brief. Pin stories, export as Markdown, HTML or email, or send it to a verified inbox. |
| 💡 **Curiosity Cards** | A collection page (`/curiosity.html`) of engineering deep dives, postmortems, papers and conference talks: netcode and rendering from Riot, Rockstar, Epic and Naughty Dog, plus infrastructure from Google, Meta, Netflix, Uber, Cloudflare, Discord and others. Browse by theme, format, company or technology. New posts are curated automatically, and you can add any card to a brief. |
| 🔎 **[Research Desk](https://getinformdaily.com/research.html)** | Search publisher evidence, ask for analysis with citations and download notes. Watch up to six topics and get alerts in your Inbox. |
| 🎯 **Personal impact** | Save your package versions and cloud regions to check whether a vulnerability or outage affects you. If there isn't enough evidence, it says **Unknown** instead of guessing. |
| ⭐ **For You** | Follow publications, topics and authors to get a ranked feed built around your interests. |

## How sources work

- Every source is reviewed for English content, a reputable publisher and permission to use its feed. Each one is listed in the **[source directory](https://getinformdaily.com/sources.html)**.
- Every feed is refreshed twice a day, at **08:00 and 20:00 IST**. The busiest newsrooms, security advisories and status pages are also checked at **02:00 and 14:00 IST**. A source that hasn't posted lately is marked *quiet*, not *failed*.
- Authors can submit their full text with permission in the **[author workspace](https://getinformdaily.com/contribute.html)**. The owner approves it, and the author can withdraw permission at any time.

More: [About](https://getinformdaily.com/about.html) · [Source standards](https://getinformdaily.com/trust.html) · [Privacy & controls](https://getinformdaily.com/privacy.html)

---

## Run locally

Requires **Python 3.12+** and **Node.js 24.x**.

```sh
uv sync --frozen
npm ci
NEWS_DATABASE_URL=sqlite:///./informa.db uv run uvicorn app.server:app --reload
```

See [.env.example](.env.example) for the AI and email settings.

**Tests** (these use fixtures and never contact publishers):

```sh
npm run lint && npm run build && npm test
uv run ruff check app tests scripts main.py
uv run pytest -q
```

**Live source check** (only when diagnosing a feed, because it contacts publishers):

```sh
uv run python -m scripts.check_sources --source hacker-news
```

## Docs

| Guide | What's inside |
|---|---|
| [HTTP API](docs/API.md) | Every endpoint, including Curiosity Cards and briefs |
| [Deployment](docs/LAUNCH.md) | Vercel, database, email and environment setup |
| [Release flow](docs/RELEASE-FLOW.md) | Staging first, then a reviewed pull request into main |
| [Source network](docs/SOURCE-NETWORK.md) | How sources are validated and promoted |
| [English source policy](docs/ENGLISH-SOURCE-POLICY.md) | Rules for adding and keeping sources |
| [Product](docs/PRODUCT.md) | Product direction and competitive review |
| [Security audit](docs/SECURITY-AUDIT-2026-11-21.md) | Latest audit and fixes |
