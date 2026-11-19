# Feed Source Recovery Implementation Plan

> **For agentic workers:** Native implementation requested by the user; complete the steps in order and verify each source path.

**Goal:** Remove or repair the seven production feed failures using publisher-approved integrations and leave the remaining active feeds schedulable and observable.

**Architecture:** Retire connectors that require unavailable paid access, deny fetches, duplicate a rate-limited publisher endpoint, or cannot produce valid metadata; keep their public alternatives active. Replace the dead robotics feed with an officially syndicated feed whose publisher permits commercial RSS use with attribution. Make configured pauses authoritative over old database state and expose safe transport failure classes.

**Tech Stack:** Python 3.12+, FastAPI, HTTPX, Feedparser, SQLAlchemy, pytest.

**Spec:** User request to fix each currently failing source end-to-end.

## Global Constraints

- Keep publisher attribution and canonical source links intact.
- Do not bypass access controls, paid API requirements, robots rules, or publisher reuse terms.
- Preserve unrelated working-tree changes.
- Keep all source URLs public HTTPS endpoints and validate source packs.

## Review Focus

- Persisted `enabled=true` must not reactivate a source explicitly paused in code.
- A disabled connector must not be polled and must not keep its archived items visible after the next scheduled refresh.
- A transport failure must report a safe, actionable class without exposing exception text or secrets.
- Replacing Robohub must retain Robotics coverage and required TechXplore attribution.
- VentureBeat's sitemap and RSS must not hammer the same host in parallel.

---

### Task 1: Make source pauses authoritative

**Files:** `app/sources.py`, `app/ingestion.py`, `app/launch_store.py`, `tests/test_refresh_reliability.py`

- [ ] Add failing tests proving configured-disabled sources stay paused when the database says enabled, are not selected by `refresh_plan`, and are disabled in persisted source state during refresh.
- [ ] Run those tests and confirm they fail for the current state-override behavior.
- [ ] Implement effective enabled state as `source.enabled and stored_enabled` and synchronize configured-disabled records in `refresh_sources`.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Repair the source registry

**Files:** `app/sources.py`, `app/source_catalog.json`, `tests/test_global_discovery.py`, `tests/test_source_network.py`

- [ ] Add failing registry tests for the four permanent/duplicate failures being paused, their accessible publisher alternatives remaining active, and the replacement robotics feed metadata.
- [ ] Replace the Robohub source-pack entry with TechXplore Robotics at its official RSS endpoint, retain attribution, and document its official feed permission in source metadata.
- [ ] Pause Tech in Asia pending permitted access; pause Hashnode Global GraphQL while retaining Hashnode Townhall RSS; pause the duplicate VentureBeat sitemap while keeping its RSS at a lower polling cadence; pause Moneycontrol's metadata-incomplete HTML listing while keeping its official RSS and sitemap.
- [ ] Run focused registry tests and validate all 501 source records load with unique IDs.

### Task 3: Improve transient failure diagnosis

**Files:** `app/news.py`, `tests/test_source_feeds.py`

- [ ] Add failing tests for timeout, DNS/connect, TLS, and generic transport exceptions.
- [ ] Map exceptions to bounded, non-sensitive error codes while preserving HTTP status-based errors such as `rate_limited` and `access_denied`.
- [ ] Run feed handling tests.

### Task 4: Verify and release

**Files:** intended files from Tasks 1–3 only.

- [ ] Run focused and full Python tests plus lint/build checks.
- [ ] Deploy only the intended feed-health changes while preserving the unrelated dirty work.
- [ ] Run the feeds-only production refresh and inspect `/api/ready` and `/api/sources` after completion; report disabled publisher-limited sources separately from active-source freshness.
