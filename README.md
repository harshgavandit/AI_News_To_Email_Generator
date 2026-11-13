# World Tech Brief

**World Tech Brief** is a production-ready, public-facing Global Tech & AI News Intelligence Platform with one-click mailbox delivery. It continuously aggregates, filters, sanitizes, and synthesizes high-signal technology news across frontier AI research labs, global industry newsrooms, regional hubs, engineering platforms, and creator channels.

Readers can browse the real-time Reading Room, pin stories of interest, customize an intelligence profile, or immediately receive today's top 5 global stories delivered directly to their inbox with one click.

Live Demo: [ai-news-to-email-generator.vercel.app](https://ai-news-to-email-generator.vercel.app)

---

## Key Platform Capabilities

### 1. Global Multi-Category Feed Matrix
Upstream aggregation spans vetted RSS/Atom feeds and YouTube creators across five structured categories:
- **AI & Frontier Labs:** OpenAI News, Anthropic News & Research, Google DeepMind, Google Research, Meta AI Engineering, Hugging Face Blog, arXiv cs.AI, Microsoft Research, LangChain Blog, and Simon Willison.
- **Global Tech & Industry:** TechCrunch, The Verge, Ars Technica, WIRED, MIT Technology Review, BBC Technology, and The Guardian Tech.
- **World & Regional Tech:** Rest of World (Global emerging markets), Tech in Asia (APAC), Sifted (Europe), Hacker News (Frontpage), TechCabal (Africa), SCMP Technology (Asia), The Indian Express Technology (India), and LatamList (Latin America).
- **Engineering & Cloud:** The GitHub Blog, InfoQ, AWS News, Cloudflare Blog, Vercel Changelog, Kubernetes Blog, PostgreSQL News, NVIDIA Technical Blog & Newsroom, and BleepingComputer.
- **Creator & Video Insights:** Curated video feeds from Matthew Berman, AI Engineer, Andrej Karpathy, Two Minute Papers, and Hugging Face.
- **Status Monitors:** Microsoft Azure, Google Cloud Status, Cloudflare Status, and GitHub Status.

### 2. Strict Content Sanitization Pipeline
- **Sponsor & Promotional Stripping:** Automatically removes video sponsor pitches (*"Thanks to... for sponsoring"*, *"Use code..."*, *"Apply for a pass"*), social link trees (Twitter/X, Discord, Instagram, Spotify, Patreon, TikTok), hashtags, timestamps, and raw URLs.
- **Schema Normalization:** Normalizes all articles into a uniform schema:
  `{ id, title, cleanSummary, whyItMatters, category, region, sourceName, sourceUrl, publishedAt, readingTimeMinutes }`.
- **Health Indicators:** Replaces intrusive warning banners with a subtle live status pill (`"Live • 40 Sources Active"`) accompanied by a hover popover detailing source check timestamps and availability.

### 3. High-Signal Reading Room & Above-The-Fold UX
- **Instant Hero Action Bar:** Directly in the hero section, readers can enter an email address, click **`Send Today's Global Top 5 Brief ✦`**, and optionally opt into automatic daily morning delivery at 8:00 AM local time.
- **Unified Split-Screen Workspace:**
  - **Left Column (65% width):** The Global Reading Room with category filter pills (`All Global`, `AI & LLMs`, `Engineering & Dev`, `Startups & Venture`, `Big Tech`, `APAC / EU / Global`, `Video Briefs`), time windows (`24h`, `7d`, `30d`), and instant debounced search.
  - **Right Column (35% width):** Live Brief Builder & Preview Drawer, allowing readers to configure, preview, and dispatch custom digests without losing page context.
  - **Mobile Experience:** Seamlessly adapts into an off-canvas tabbed bottom sheet.
- **Card Insights & Pinning:**
  - Uniform card heights with 3-line clamped clean summaries.
  - Contextual **"Why it matters"** 1-line insight badges on every story.
  - Interactive **`+ Pin to Brief`** toggle buttons on story cards to hand-pick articles for inclusion in custom digests.

### 4. Frictionless Brief Builder & AI Synthesis
- **Interactive Topic Chips:** Clickable chips (`AI Agents`, `RAG & Production AI`, `Cloud & Backend`, `Semiconductors`, `Cybersecurity`, `Open Source`, `Global Tech Policy`, `Venture Deals`) pair with an optional custom refinement prompt.
- **Depth & Format Controls:**
  - Brief Length: `3 stories`, `5 stories`, `10 stories`.
  - Reading Style: `Executive Bullet Points`, `Deep Technical Breakdown`, `Quick 2-Minute Skim`.
- **Structured Output:** Synthesizes a macro overview, ranked articles with key takeaways, and a "Quick Hits Around the World" section linking three notable one-line global updates.

### 5. Public One-Click Mailbox Delivery & Deliverability
- **Public Delivery Flow:** Replaces owner-only access keys with an open delivery flow. Any reader can verify their mailbox once and receive up to 3 briefs per UTC day.
- **Multi-Provider Transactional Email Engine:**
  - **Resend API:** Native support via `RESEND_API_KEY`.
  - **Postmark API:** Native support via `POSTMARK_SERVER_TOKEN`.
  - **Custom SMTP:** Connect via standard `SMTP_URL`.
  - **Gmail SMTP:** Out-of-the-box fallback via `MY_EMAIL` and `APP_PASSWORD`.
- **Responsive HTML Template:** Single-column 600px max-width layout, inline CSS, dark-mode compatible, high-contrast typography, and CAN-SPAM/GDPR compliant 1-click unsubscribe headers and footers.
- **Abuse Prevention:** Per-IP hourly quotas (max 5 delivery attempts/hour per IP), rate-limited verification codes, and Cloudflare Turnstile bot checks.
- **Automated Morning Scheduler:** Optional daily 8:00 AM delivery calculated dynamically across IANA timezones with DST transition awareness and atomic worker claiming.

---

## Getting Started

### Prerequisites
- Python 3.12+ (or 3.14)
- Node.js 18+ (for frontend static asset validation)

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/harshgavandit/AI_News_To_Email_Generator.git
cd AI_News_To_Email_Generator

# Install Python dependencies
pip install -e .

# Install dev dependencies
pip install pytest ruff
```

### 2. Environment Configuration
Copy the example environment file:
```bash
cp .env.example .env
```

Configure your `.env` variables:
```ini
# AI Summarization
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Public Delivery Origin
PUBLIC_ORIGIN=https://ai-news-to-email-generator.vercel.app

# Public One-Click Delivery
PUBLIC_EMAIL_ENABLED=1
MAIL_SESSION_SECRET=replace-with-at-least-32-random-characters
MAIL_PILOT_MODE=0

# Transactional Email Providers (Choose one)
# Option A: Resend
RESEND_API_KEY=re_123456789

# Option B: Postmark
# POSTMARK_SERVER_TOKEN=your-postmark-token

# Option C: SMTP URL
# SMTP_URL=smtp://user:pass@smtp.mailtrap.io:587

# Option D: Gmail App Password
MY_EMAIL=your-email@gmail.com
APP_PASSWORD=your-16-char-gmail-app-password

# Bot Protection
TURNSTILE_SITE_KEY=your-turnstile-site-key
TURNSTILE_SECRET_KEY=your-turnstile-secret-key

# Storage (PostgreSQL for production, SQLite for local dev)
NEWS_DATABASE_URL=sqlite:///brief.sqlite
```

### 3. Running Locally
Run the development server:
```bash
uvicorn app.server:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Testing & Verification

Run the full end-to-end test suite:
```bash
# Run pytest test suite (50 test cases covering feed health, quotas, scheduling, and UI endpoints)
python -m pytest

# Run frontend build verification
npm run build

# Run JavaScript syntax and asset link checks
npm run lint
```

---

## License
Apache-2.0
