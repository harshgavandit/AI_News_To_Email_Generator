# Informa AI HTTP API

The running app exposes OpenAPI at `/openapi.json` and Swagger UI at `/api/docs`. JSON errors include a `detail` field. API responses include an `X-Request-ID` for log correlation. A `429` may include `Retry-After`.

## Discover stories

`GET /api/news?hours=168&q=vector+search&sort=relevance&limit=12`

- `hours` accepts `12`, `24`, `168`, or `720`.
- `topic`, `source`, `publisher`, `kind`, and `region` narrow the result. Get source IDs and categories from `GET /api/sources`.
- `sort` accepts `latest`, `oldest`, or `relevance`. Relevance requires search terms and gives more weight to headline matches. Relevance without a query uses newest-first order.
- `limit` ranges from 1 to 50. Pass the previous page’s `next_cursor` with the same query, filters, and sort. Pages reflect the rolling publication window. If the underlying archive changes while paging, results can move.
- `freshness` reports the selected feeds’ last check, last success, and counts. `force=true` bypasses the archive page cache and can request a background refresh. Direct RSS mode applies a per-process fetch cooldown. `refresh_requested` means a refresh task was requested, and the response still represents the current archive.

## Build and deliver a brief

Post JSON to `/api/digest` with `edition` (`world` or `personal`), `hours`, and `top_n` (1–10). A personal edition can also specify `name`, `focus`, `topics`, `persona`, `style`, `sources`, and ordered `pinned_ids`. The response contains the preview, Markdown, HTML, and delivery metadata. The personal edition requires a configured OpenAI key.

Add `?stream=true` to receive newline-delimited JSON. Events contain a numbered `stage`, a final `result`, or an `error` with a `status` and optional `retry_after`. Errors emitted after streaming starts are carried in the stream rather than the HTTP status.

Story `summary_basis` is `ai_feed_summary`, `publisher_excerpt`, or `headline_only`. A personalized result also reports synthesis status, the number of AI summaries, and whether final ordering came from the model or from the initial selection. Original titles and links always come from the feed records.

`POST /api/email` requires the owner bearer token and the signed, expiring digest response. The recipient is fixed by server configuration. The `/api/mail` routes verify an inbox before sending a stored preview and accept an explicit opt-in for the daily global edition. `/api/deliver/webhook` requires a verified inbox and accepts supported HTTPS Slack and Teams webhook URLs.

## Health and job routes

`GET /api/health` reports service liveness and configuration. `GET /api/ready` returns `503` if the archive is missing or lacks a fresh feed. Job routes require a configured scheduler token. See [release operations](LAUNCH.md) for setup, quotas, and delivery monitoring.
