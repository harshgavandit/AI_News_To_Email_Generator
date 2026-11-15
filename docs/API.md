# Informa AI HTTP API

The running app exposes OpenAPI at `/openapi.json` and Swagger UI at `/api/docs`. JSON errors include a `detail` field. API responses include an `X-Request-ID` for log correlation. A `429` may include `Retry-After`.

## Discover stories

`GET /api/headlines` returns reviewed developing coverage and a ranked selection of recent articles from enabled reporting feeds. The homepage uses it independently of the Reading Room’s time window and sort.

`GET /api/news?hours=168&q=vector+search&sort=relevance&limit=12`

- `hours` accepts `12`, `24`, `168`, or `720`.
- `topic`, `source`, `publisher`, `kind`, `region`, and `coverage` can be combined. `GET /api/sources` returns the `topics`, `regions`, and `coverage_types` ID-to-label maps, plus `region_id`, `language`, provenance, and freshness for each feed. `region` describes the publisher's coverage, so the location mentioned in a story may differ. Use `coverage=reporting` for independent reporting or `coverage=advisory` for official cybersecurity advisories.
- `facets.topics` and `facets.regions` count articles in the active publication window before pagination. Each facet applies the other filters while ignoring its own selection. `source_counts` counts stories by source group while ignoring the `source` selection.
- `sort` accepts `latest`, `oldest`, or `relevance`. Search matches terms in titles, publisher names, or feed excerpts. It folds capitalization and Latin accents and tolerates punctuation such as the hyphen in `zero-day`. Relevance gives extra weight to titles with the full phrase. Relevance without a query uses newest-first order.
- `limit` ranges from 1 to 50. Pass `next_cursor` with the same query, filters, and sort. The cursor keeps the original publication window, returned as `window_ends_at`, for up to 24 hours. Late-arriving stories and edits within that window can still change results.
- `freshness` reports the selected feeds’ last check, last success, and counts, including the selected region. `force=true` bypasses the archive page cache and can retry matching failed or overdue feeds. Direct RSS mode applies a per-process fetch cooldown. `refresh_requested` means a background task was requested and the response still represents the current archive.

## Build and deliver a brief

Post JSON to `/api/digest` with `edition` (`world` or `personal`), `hours`, and `top_n` (1–10). Both editions accept `topic`, `region`, `sources`, and ordered `pinned_ids`. Topic and region apply to automatic story selection. Explicit pins can include stories outside that scope. A personal edition can also specify `name`, `focus`, free-text `topics`, `persona`, and `style`. The response contains the preview, Markdown, HTML, and delivery metadata. The personal edition requires a configured OpenAI key.

Add `?stream=true` to receive newline-delimited JSON. Events contain a numbered `stage`, a final `result`, or an `error` with a `status` and optional `retry_after`. Errors emitted after streaming starts are carried in the stream rather than the HTTP status.

Story `summary_basis` is `ai_feed_summary`, `publisher_excerpt`, or `headline_only`. A personalized result also reports synthesis status, the number of AI summaries, and whether final ordering came from the model or from the initial selection. Original titles and links always come from the feed records.

`POST /api/email` requires the owner bearer token and the signed, expiring digest response. The recipient is fixed by server configuration. The `/api/mail` routes verify an inbox before sending a stored preview and accept an explicit opt-in for the daily global edition. `/api/deliver/webhook` requires a verified inbox and accepts supported HTTPS Slack and Teams webhook URLs.

## Health and job routes

`GET /api/health` reports service liveness and configuration. `GET /api/ready` returns `503` if the archive is missing or lacks a fresh feed. Job routes require a configured scheduler token. See [release operations](LAUNCH.md) for setup, quotas, and delivery monitoring.
