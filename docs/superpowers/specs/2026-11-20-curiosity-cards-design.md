# Curiosity Cards Design

## Intent

Give Informa AI readers a dedicated place to discover how real systems and engineering teams work. Cards provide a source-attributed headline, company, short source-grounded summary, tags, estimated reading time, and a direct publisher link. Readers can add a card to a manual brief or opt it into their verified scheduled email.

## Goals

- Seed the collection with the Google monorepo paper, user-supplied Anthropic/OpenAI/FlashAttention links, “Attention Is All You Need,” and additional source-verified engineering stories from Anthropic, OpenAI, Meta, Uber, and Netflix.
- Discover additional engineering stories from reviewed RSS, APIs, and publisher listing integrations already supported by the ingestion layer.
- Rank architecture, infrastructure, scaling, reliability, distributed-systems, model-systems, and engineering-process insights above announcements and promotional posts.
- Deduplicate source URLs and normalized titles against the seeded collection and archive.
- Generate AI summaries for eligible archive stories from their publisher excerpts using the existing digest model and cache. Curated landmark and company-story seeds carry concise source-grounded editorial abstracts with their basis labeled accurately.
- Integrate cards with existing manual brief pins and deliver a small, user-managed selection in opted-in scheduled email.
- Keep source polling inside the existing 08:00 and 20:00 IST feed sweeps.

## Non-goals

- Reproducing article bodies or bypassing paywalls.
- Crawling arbitrary URLs or searching the open web from production requests.
- Increasing feed refresh frequency or triggering a source refresh when this feature is opened.
- Treating promotional announcements or unsubstantiated model-generated claims as engineering analysis.

## Constraints

- Continue using PostgreSQL/SQLite compatibility and additive migrations.
- Use reviewed source records only. Publisher listing sources must check robots.txt, stay on the publisher host, and fetch only bounded public metadata.
- Validate English at the article level and do not translate foreign-language articles.
- Store at most a bounded metadata snapshot for scheduled card selections; never store full article text.
- Scheduled selection is private to the verified mailbox, requires same-origin writes, and is independently removable.
- Preserve existing manual brief pins, email verification, quotas, unsubscribe flow, and scheduled delivery behavior.

## Approaches

1. **Static editorial list only:** reliable and copyright-safe, but cannot surface new engineering work.
2. **Score the whole news archive:** easy to wire to current data, but risks promoting news releases, generic articles, and thin excerpts into an engineering collection.
3. **Hybrid curated seeds plus reviewed-source discovery (chosen):** verified evergreen records preserve the requested papers and links; new cards are scored from existing engineering/research feeds, deduplicated, and summarized from source excerpts. This adds useful discovery without arbitrary crawling or another feed-refresh schedule.

The user delegated technical ownership and requested direct implementation, so the hybrid choice is the implementation decision.

## Experience

- Replace the single static spotlight with a dedicated Curiosity Cards section on the Reading Room.
- Show responsive cards with publisher attribution, company, year/date, tags, estimated reading time, a clearly identified AI or editorial source summary, and an external original-source link. Reveal long collections progressively.
- Include an “Add to brief” action using the existing ten-story brief pin limit.
- For verified inboxes, provide a separate toggle to include/remove a card from their scheduled Curiosity selection. Limit scheduled selections to five and expose the current selected count in the section.
- If an inbox is not verified, route the reader to the existing brief-builder email workflow; after verification they can manage scheduled selections here.

## Data and discovery

- Add `app/curiosity.py` as the curated seed catalog, quality scorer, deduplicator, card projection, and scheduled snapshot validator.
- Reuse the archive and its source allowlist. Auto-discovery is restricted to English, excerpt-bearing engineering/research/article/publisher records from reviewed sources. Use explicit engineering signals and reject promotional signals. No page-body scraping is introduced.
- Add a small number of reputable source connectors where official permissions and existing parser behavior support them: Meta Engineering RSS, Stripe and Uber public engineering listing metadata (robots-checked, same-host, bounded), Razorpay Engineering and Aleksa Gordić Medium RSS.
- Add an indexed, bounded `Store.curiosity_candidates` query and a private mailbox selection table. Existing Article rows remain canonical; selected cards store only a reduced snapshot so scheduled editions survive archive retention.
- Archive article summaries use `build_digest` with the technical persona and existing persistent summary cache. If model output is unavailable, preserve the publisher excerpt and mark its basis; do not fabricate a replacement. Seed summaries are labeled as curated source abstracts.

## APIs and delivery

- `GET /api/curiosity?limit=...` returns cards from seeds plus archive candidates, with stable IDs and source attribution. Cache the public response briefly; no feed fetch occurs.
- `GET /api/mail/config` returns selection IDs and subscription state only for a verified session, with private/no-store caching.
- `PUT /api/mail/curiosity` accepts only a bounded list of card IDs, requires a verified inbox and same-origin write, resolves each ID server-side, and stores reduced metadata snapshots. Unknown IDs and over-limit lists are rejected.
- Manual newsletters use existing `pinned_ids` and digest preview/signature flow. Seed IDs resolve through the curated catalog; archive IDs resolve through the normal Store.
- Scheduled delivery appends selected Curiosity Cards to both direct and batched daily email using escaped text and canonical source URLs. It performs no source requests and no model calls in the delivery loop.

## Verification

- Unit tests for source allowlisting, English validation, signal scoring, promotional rejection, URL/title deduplication, stable seeds, archive lookup, and cache-safe API projection.
- Fixture-only parser tests for robots rules, path allowlists, bounded article metadata, and rejected disallowed paths; no test contacts publishers.
- Client tests for card rendering, accessible add/remove interactions, pin limits, selection toggles, and graceful API failure.
- Isolated SQLite tests for verified selection persistence, authorization/origin checks, manual digest inclusion, and direct/batched scheduled email summary/link inclusion.
- Run the full Python and frontend suites, lint, build, and `git diff --check`. Verify no publisher refresh endpoint was invoked.
