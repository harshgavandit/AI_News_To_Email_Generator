# Public Digest Implementation Plan

> Inline execution with test-driven development and verification before completion.

**Goal:** Ship larger browse/search coverage and free, verified, on-demand digest delivery.

**Architecture:** FastAPI/Vercel plus durable PostgreSQL. Separate source ingestion, selection, and delivery modules; SQLite exercises the shared contracts locally.

**Spec:** `docs/superpowers/specs/2026-11-13-public-digest-design.md`

## Global constraints

Three digest emails per mailbox per UTC day. No subscriptions or recurring mail. No secret values in source, logs, or API responses. Maintain existing previews and owner delivery. Public production mail is off until configured.

## Review focus

Quota races across workers, forged or replayed verification, edited previews, source outages, stable pages, and failure after provider acceptance.

- [ ] Write tests for canonical URLs, source history and pagination, and a relevant candidate older than the newest stories; implement registry, ingestion, store, and ranking shortlist.
- [ ] Write tests for verification and concurrent daily quotas; implement captcha, single-use codes, session, signed-identity sends, durable admission and retry semantics.
- [ ] Wire filters, source controls, verification and send UI; exercise offline integration and responsive browser behavior.
- [ ] Verify provider configuration, deployment, and CI. Keep the public email switch off when launch infrastructure is absent.
