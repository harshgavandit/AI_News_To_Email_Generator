# Curiosity Cards Implementation Plan

> **For agentic workers:** Use the native execution method selected by the user’s explicit implementation and technical-ownership request. Follow TDD task by task. Do not fetch live publisher feeds during tests or feature verification.

**Goal:** Build a source-backed Curiosity Cards collection that discovers engineering insights, supports manual brief pins, and sends verified user selections in scheduled email.

**Architecture:** Combine verified evergreen records with quality-ranked engineering/research articles already present in the archive. Use existing source integrations and the twice-daily sweep, article summary cache, brief builder, verified mailbox cookie, and email renderer; add only a bounded mailbox-scoped selection store and Curiosity API.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy (SQLite/PostgreSQL), pytest, plain browser JavaScript, jsdom, existing OpenAI digest agent, RSS/publisher-metadata integrations.

**Spec:** `docs/superpowers/specs/2026-11-20-curiosity-cards-design.md`

## Global Constraints

- Publisher refresh stays at 08:00 and 20:00 IST.
- Read only reviewed RSS/API feeds or same-host public metadata allowed by robots.txt.
- Do not store full articles, bypass paywalls, or translate non-English content.
- Keep user selections private to the verified mailbox and cap them at five scheduled cards.
- Preserve the existing ten-story manual pin limit, email quotas, explicit subscription opt-in, and unsubscribe behavior.
- Use source-grounded AI summaries and retain excerpt fallback when model output is unavailable.

## Review Focus

- Duplicate canonical URLs or equivalent normalized titles across editorial seeds and archive — add tests asserting one card and stable seed priority.
- Promotions, thin excerpts, and non-engineering releases entering discovery — add tests for signal thresholds, exclusions, and excerpt requirements.
- Publisher robots/path rules changing or disallowing a page — add fixture tests that reject disallowed listing/article paths and never follow off-host URLs.
- Unverified/cross-origin mail selection writes or arbitrary article IDs — add endpoint tests for missing session, mismatched Origin, unknown IDs, and over-limit input.
- Selected scheduled cards outliving archive retention or containing unsafe markup — add tests for bounded snapshot resolution, HTML escaping, original-link validation, and removal.

---

### Task 1: Curiosity discovery, seed catalog, source connectors, and API

**Files:**
- Create: `app/curiosity.py`
- Modify: `app/sources.py`
- Modify: `app/launch_store.py`
- Modify: `app/server.py`
- Test: `tests/test_curiosity.py`
- Test: `tests/test_source_feeds.py`

**Interfaces:**
- `app.curiosity.build_curiosity_cards(store, *, limit=24) -> list[dict]` returns stable, already-attributed card records with `id`, `title`, `company`, `publisher`, `published_at`, `year`, `summary`, `summary_basis`, `tags`, `read_minutes`, `url`, `source_id`, and `description`.
- `app.curiosity.curiosity_article(ident) -> dict | None` resolves only a curated seed.
- `Store.curiosity_candidates(source_ids, *, hours=2160, limit=200) -> list[dict]` returns bounded eligible archive rows.
- `GET /api/curiosity?limit=24` validates `limit` (1–24), returns `{cards, updated_at, selection_limit}`, and does not invoke ingestion.
- Curiosity article IDs are valid existing `DigestRequest.pinned_ids` IDs; `prepare_digest` resolves curated seeds if the archive does not contain them.

- [x] **Step 1: Add failing curation tests** for requested seed URLs, source metadata, archive candidates, English excerpt checks, quality/promotion ranking, and URL/title deduplication.
- [x] **Step 2: Run the focused tests and confirm the initial failures.**
- [x] **Step 3: Add the seed catalog**, including the user-provided links and additional source-verified engineering stories from Anthropic, OpenAI, Meta, Uber, and Netflix. Store concise abstracts only.
- [x] **Step 4: Add archive selection and deterministic ranking** restricted to reviewed English engineering/research records and selected official engineering news feeds; deduplicate and reject promotional/low-signal entries.
- [x] **Step 5: Add the bounded store query and API**. Generate AI summaries for eligible archive cards through the existing technical digest/cache and label curated abstracts accurately.
- [x] **Step 6: Add reviewed sources** for Meta Engineering RSS, Stripe and Uber robots/path-checked public listing metadata, Razorpay Engineering Medium RSS, and Aleksa Gordić’s profile RSS. Use English checks and fixture-only parsing.
- [x] **Step 7: Add regression cases** for the review focus; fixture parser tests perform no network calls.

### Task 2: Curiosity cards UI and manual Brief Builder integration

**Files:**
- Create: `public/curiosity.js`
- Modify: `public/index.html`
- Modify: `public/app.js`
- Modify: `public/polish.css`
- Test: `tests/test_curiosity.py`
- Test: `tests/client/curiosity.test.mjs`
- Test: `tests/test_curiosity.py`

**Interfaces:**
- `renderCuriosityCards(container, cards, {pinnedIds, scheduledIds, onPin, onToggleScheduled, verified, scheduledEnabled})` creates cards with text-only DOM construction and accessible controls.
- The section fetches only `GET /api/curiosity`; card source links are external and use `noopener noreferrer`.
- `onPin(card)` adds/removes the normal `state.pins` record and opens the existing Brief Builder; digest generation stays on the existing API path.

- [x] **Step 1: Replace the static spotlight test** with DOM tests for card content, source context, summary basis, tags, time estimates, safe links, controls, empty state, and progressive reveal.
- [x] **Step 2: Run the client tests and verify the missing-renderer failure.**
- [x] **Step 3: Implement `renderCuriosityCards`** with text-only DOM construction, HTTPS links, accessible states, bounded tags, and attribution labels.
- [x] **Step 4: Replace the static card** with a responsive section, load `/api/curiosity` without ingestion, and wire card pins into the existing Brief Builder.
- [x] **Step 5: Add styling** with focus/hover states, responsive sizing, and reduced-motion behavior.
- [x] **Step 6: Add manual brief coverage** for a curated seed absent from the archive.
- [x] **Step 7: Re-run focused frontend and Python checks.**

### Task 3: Verified scheduled selections and email delivery

**Files:**
- Modify: `app/launch_store.py`
- Modify: `app/public_mail.py`
- Modify: `app/mail_schedule.py`
- Modify: `app/mail_batches.py`
- Modify: `public/app.js`
- Modify: `public/curiosity.js`
- Test: `tests/test_mail_schedule.py`
- Test: `tests/client/curiosity.test.mjs`

**Interfaces:**
- `Store.curiosity_selection(mailbox) -> list[dict]` reads reduced snapshots from `brief_mail_curiosity`.
- `Store.save_curiosity_selection(mailbox, cards) -> None` atomically replaces a maximum of five reduced snapshots; an empty list clears the selection.
- `GET /api/mail/config` adds private fields `scheduled_enabled`, `curiosity_ids`, and `curiosity_selection_limit` only for verified inboxes.
- `PUT /api/mail/curiosity` accepts `{article_ids: [...]}`, requires a verified mailbox and same-origin write, resolves each ID through current Curiosity cards, and stores validated metadata snapshots.
- `append_curiosity_section(brief, cards) -> brief` appends escaped headlines, concise summaries, company/publisher attribution, and canonical original links to Markdown and HTML.

- [x] **Step 1: Add store/API behavior tests** for verified read/write, anonymous rejection, origin validation, unknown IDs, max-five selection, private config, and removal.
- [x] **Step 2: Run the focused schedule tests and confirm initial failures.**
- [x] **Step 3: Add the additive SQLite/PostgreSQL table and Store selection methods**; persist reduced metadata snapshots only.
- [x] **Step 4: Extend private mail configuration and add the verified same-origin `PUT /api/mail/curiosity` route.**
- [x] **Step 5: Wire card toggles** to the existing verification flow; delivery remains behind explicit scheduled opt-in.
- [x] **Step 6: Append selections to direct and batched scheduled mail** using escaped content and canonical source URLs, without feed/model calls in the delivery loop.
- [x] **Step 7: Add mocked direct and batch delivery tests** for summaries, attribution, links, and removal.

### Task 4: Full verification and release readiness

**Files:**
- Review: all files from Tasks 1–3
- Test: `tests/test_curiosity.py`, `tests/test_mail_schedule.py`, `tests/test_source_feeds.py`, `tests/client/curiosity.test.mjs`

- [x] **Step 1: Run focused tests** for curation, parser, client, and scheduled email paths.
- [ ] **Step 2: Run the complete Python suite** with `pytest -q` and record the final pass/fail counts. On this Windows Python 3.14 sandbox, the broader existing mail tests stall in Starlette `TestClient`; the feature-specific tests are run separately and pass. CI remains the complete-suite gate.
- [x] **Step 3: Run the full frontend suite, lint, and build** with `npm test`, `npm run lint`, and `npm run build`.
- [x] **Step 4: Run `git diff --check` and inspect the full diff** for accidental feed runs, unbounded network paths, unsafe HTML, or unrelated changes.
- [ ] **Step 5: Verify production only through read-only static/API/browser requests if deployment is explicitly part of the active request.** Do not call feed refresh/admin endpoints or claim scheduled delivery without the isolated delivery proof.
