# Informa AI HTTP API

The running app exposes OpenAPI at `/openapi.json` and Swagger UI at `/api/docs`. JSON errors include a `detail` field. API responses include an `X-Request-ID` for log correlation. A `429` may include `Retry-After`.

## Discover stories

`GET /api/headlines` returns reviewed developing coverage and a ranked selection of recent articles from enabled reporting feeds. The homepage uses it independently of the Reading Room’s time window and sort.

`GET /api/news?hours=168&q=vector+search&sort=relevance&limit=12`

- `hours` accepts `12`, `24`, `168`, or `720`.
- `topic`, `subject`, `source`, `publisher`, `kind`, `region`, `language`, and `coverage` can be combined. `GET /api/sources` returns `topics`, `subjects`, `regions`, `languages`, and `coverage_types` maps, plus provenance, integration type, last successful check, and latest retained publication time for each source. `region` describes the publisher's coverage. Use `coverage=article` for articles and tutorials, `source=medium` for selected Medium feeds, or `subject=cloud` for cloud infrastructure across topics.
- `facets.topics`, `facets.regions`, and `facets.languages` count articles in the active publication window before pagination. Each facet applies the other filters while ignoring its own selection. `source_counts` counts stories by source group while ignoring the `source` selection.
- `sort` accepts `latest`, `oldest`, or `relevance`. Search matches terms in titles, publisher names, feed excerpts, and retained author names and tags. It folds capitalization and Latin accents and tolerates punctuation such as the hyphen in `zero-day`. Relevance gives extra weight to titles with the full phrase. Archive and direct-feed search use the same weights. Relevance without a query uses newest-first order.
- `limit` ranges from 1 to 50. Pass `next_cursor` with the same query, filters, and sort. The cursor keeps the original publication window, returned as `window_ends_at`, for up to 24 hours. Late-arriving stories and edits within that window can still change results.
- `freshness` reports the selected feeds’ last check, last success, and counts, including the selected region. `force=true` bypasses the archive page cache and can retry matching failed or overdue feeds. Direct RSS mode applies a per-process fetch cooldown. `refresh_requested` means a background task was requested and the response still represents the current archive.

## Reading and recommendations

`GET /api/articles/{article_id}` returns an enabled, retained article, up to five related articles, a reading notice, and the source excerpt with `limited_source: true`. Missing or paused-source articles return `404`. There is no arbitrary URL fetch or full-article extraction. The frontend uses `/?article=<id>#reading-room` for shareable reader links. These links resolve while the record remains in the archive (currently 90 days).

Article records may include `author`, `tags`, `original_url`, `discussion_url`, `points`, `comments_count`, and a reviewed `thumbnail_url`. These fields are bounded and sanitized before storage and on read. Images are loaded directly from a limited list of reviewed hosts with no referrer. `reading_time_basis` distinguishes a publisher-provided article estimate from the short excerpt. `reading_policy` is `excerpt`; complete article bodies are not returned.

`POST /api/recommendations` accepts a JSON object:

```json
{"topics":["software","research"],"subjects":["cloud","open-source"],"sources":["dev","github-blog"],"exclude_ids":[],"q":"","limit":24}
```

It ranks a bounded, publisher-and-topic-diverse pool from the last seven days. The response includes `articles`, `total_candidates`, `personalized`, `basis`, and `updated_at`. Each article includes `recommendation_reasons`. Interests and followed sources receive preference weights, with smaller freshness, excerpt-availability and engagement signals. A publisher diversity penalty and canonical URL deduplication reduce repetition. An empty preference set produces a diverse recent selection. This is an explainable rule-based ranking, with no model call or user identity storage. Browser interests stay local; selected preferences and at most 100 excluded read IDs are submitted per request. Responses are `no-store` and the endpoint is rate limited.

`GET /api/trending` analyzes the recent, bounded pool across reporting, developer articles, research and community sources. Counts describe observed matching records, not global popularity. It excludes future-dated records and exact canonical duplicates. The returned `query` is derived from source text so the topic chip opens a searchable phrase. `source_count` gives the number of observed source feeds.

## Build and deliver a brief

Post JSON to `/api/digest` with `edition` (`world` or `personal`), `hours`, and `top_n` (1–10). Both editions accept `topic`, `subject`, `region`, `language`, `coverage`, `sources`, and ordered `pinned_ids`. The coverage setting filters sources for automatic story selection. Explicit pins can include stories outside that scope. A personal edition can also specify `name`, `focus`, free-text `topics`, `persona`, and `style`. The response contains the preview, Markdown, HTML, and delivery metadata. The personal edition requires a configured OpenAI key. The article reader uses this same validated pipeline with one pinned story for its AI brief action.

Add `?stream=true` to receive newline-delimited JSON. Events contain a numbered `stage`, a final `result`, or an `error` with a `status` and optional `retry_after`. Errors emitted after streaming starts are carried in the stream rather than the HTTP status.

Story `summary_basis` is `ai_feed_summary`, `publisher_excerpt`, or `headline_only`. A personalized result also reports synthesis status, the number of AI summaries, and whether final ordering came from the model or from the initial selection. Original titles and links always come from the feed records.

`POST /api/email` requires the owner bearer token and the signed, expiring digest response. The recipient is fixed by server configuration. The `/api/mail` routes verify an inbox before sending a stored preview and accept an explicit opt-in for the daily global edition. `/api/deliver/webhook` requires a verified inbox and accepts supported HTTPS Slack and Teams webhook URLs.

## Health and job routes

`GET /api/health` reports service liveness and configuration. `GET /api/ready` returns `503` if the archive is missing or lacks a fresh feed. Job routes require a configured scheduler token. See [release operations](LAUNCH.md) for setup, quotas, and delivery monitoring.
