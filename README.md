# Informa AI

> **Your Personal AI News Intelligence Agent.**  
> *Discover what matters. Understand why it matters. Stay ahead without information overload.*

**Core Pillars:** Discover · Analyze · Personalize · Automate

---

Informa AI is a production-ready, autonomous Global Technology & AI News Intelligence Platform with one-click mailbox delivery. Designed with enterprise-grade editorial rigor, Informa AI aggregates, sanitizes, and synthesizes high-signal developments across frontier AI research labs, cloud engineering blogs, global tech publications, and regional intelligence hubs.

[Open Informa AI Live Platform](https://ai-news-to-email-generator.vercel.app/)

---

## Key Platform Capabilities

### 1. Multi-Perspective Intelligence (Inspired by Particle)
- **Multi-Layered Analysis:** Every story card offers distinct cognitive layers—factual narrative summary, strategic context ("Why It Matters"), and actionable key takeaways.
- **Interactive Perspective Switcher:** Switch between narrative facts and strategic implications directly on the story card without losing reading position.
- **Signal Attribution & Scoring:** Distinguishes primary reporting, official announcements, security advisories, and arXiv research preprints with publisher verification.

### 2. High-Density Dual Layouts (Inspired by Feedly)
- **Editorial Cards View:** Rich magazine cards with perspective toggles, publisher badges, reading time estimates, and one-click pinning.
- **High-Density Compact List View:** Clean tabular row layout optimized for intelligence analysts scanning 50+ headlines rapidly.
- **Source Health Transparency:** Real-time feed health indicators, last-checked timestamps, and full publisher directory across Africa, Asia-Pacific, Europe, Latin America, MENA, and North America.

### 3. Rapid Power-Reader Workflows (Inspired by Trace)
- **Fluid Keyboard Navigation:**
  - `<kbd>/</kbd>` — Instant debounced search
  - `<kbd>J</kbd>` / `<kbd>K</kbd>` — Navigate next / previous story with auto-focus
  - `<kbd>P</kbd>` — Toggle pin to custom brief
  - `<kbd>S</kbd>` — Toggle save / bookmark to local storage
  - `<kbd>B</kbd>` — Toggle Brief Builder drawer
- **1-Click Global Intelligence Top 5:** Directly in the hero section, enter an email address to dispatch the top 5 highest-signal global stories from the past 24 hours in one click, with optional 8:00 AM local time daily scheduling.

### 4. Frictionless Brief Builder & Delivery Engine
- **Customizable Depth & Perspective:** Generate tailored briefings with configurable story length (3, 5, 10 stories), style (Executive, Technical, Quick Skim), and reader perspective (Executive, Engineering, Security, Product).
- **Enterprise Multi-Provider Delivery:** Seamless transactional delivery via Resend, Postmark, custom SMTP, or Gmail OAuth with automatic fallback.
- **Responsive Dark/Light HTML Emails:** Single-column 600px max-width layout with inline CSS, dark-mode compatibility, source links, and one-click GDPR/CAN-SPAM compliant unsubscribe footer.
- **Abuse Prevention:** Rate-limited IP and mailbox dispatches, signed expiring tokens, and anti-tamper digests.

---

## Quickstart & Local Development

### Prerequisites
- Python 3.12+
- Node.js 20+

### Setup

```bash
# Clone the repository
git clone https://github.com/harshgavandit/AI_News_To_Email_Generator.git
cd AI_News_To_Email_Generator

# Install Python dependencies
uv sync --frozen

# Copy example environment configuration
cp .env.example .env

# Run local development server
uv run uvicorn app.server:app --reload --port 8000
```

Open `http://localhost:8000` in your browser.

---

## Validation & Test Suite

Verify all static assets, linting, and test suites end-to-end:

```bash
# Validate static assets and element IDs
npm run build

# Lint frontend scripts
npm run lint

# Run Python test suite
uv run pytest -q

# Format and style verification
uv run ruff check app tests scripts main.py
```

---

## Architecture & Documentation

- [Deployment and Configuration Guide](docs/LAUNCH.md)
- [REST API Specification](docs/API.md)

---

**Informa AI** · *Discover what matters. Understand why it matters. Stay ahead without information overload.*
