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
- `freshness` reports the selected feeds’ last check, last success, and counts, including the selected region. `force=true` bypasses the archive page cache and can retry matching failed or overdue feeds. A source record includes `retry_at` while it is waiting for its next eligible check. Direct RSS mode applies a per-process fetch cooldown. `refresh_requested` means a background task was requested and the response still represents the current archive.

The two broad DEV streams require a technical title, excerpt, or topic tag. The archive applies the same rule to previously retained posts, so search totals, recommendations, and reading details exclude out-of-scope records.

## Reading and recommendations

`GET /api/articles/{article_id}` returns an enabled, retained article, up to five related articles, a reading notice, and the source excerpt with `limited_source: true`. When an active, owner-approved reading permission exists, `reading` contains sanitized HTML, plain text and attribution; otherwise it is `null`. Missing or paused-source articles return `404`. Detail responses are `no-store` so withdrawn permissions are checked on the next read. There is no arbitrary URL fetch or automatic article extraction. The frontend uses `/?article=<id>#reading-room` for shareable reader links. These links resolve while the record remains in the archive (currently 90 days).

Article records may include `author`, `author_url`, `author_key`, `tags`, `original_url`, `discussion_url`, `points`, `comments_count`, and a reviewed `thumbnail_url`. These fields are bounded and sanitized before storage and on read. Images are loaded directly from reviewed hosts with no referrer. `reading_time_basis` distinguishes a publisher-provided article estimate from the excerpt. `reading_access.mode` is `excerpt`, `headline_only`, or `full_text`; full text requires a separate reviewed permission record and cannot be enabled by upstream metadata. List badges can retain their one-minute cache, while reading details always recheck permission. AI briefs continue to use publisher excerpts even when licensed text is available for reading.

Related results come from the last 30 days, using at most 200 archive candidates. Each result's `related_reason` identifies shared headline terms or a matching CVE/GHSA identifier. The additive `coverage` array contains up to five other publisher records that share a CVE/GHSA reference or have high headline overlap in the same language. The articles must be published within 72 hours of each other. Coverage may overlap with `related` and stays linked to each original article. Use `coverage=journal` to find research journal entries or `coverage=release` for official release feeds. The journal label identifies the publishing venue.

`GET /api/authors?q=writer&limit=80` returns bounded, observed author identities from the recent discovery sample. API profile URLs identify authors when supplied; RSS names without profiles are scoped to their source feed, preventing namesakes from being merged. The returned `id` can be used in recommendations. This is not an exhaustive directory of either external platform.

`POST /api/recommendations` accepts a JSON object:

```json
{"topics":["software","research"],"subjects":["cloud","open-source"],"sources":["dev","medium-codex"],"authors":[],"exclude_ids":[],"q":"Kubernetes","limit":24,"scope":{"hours":168,"coverage":"article"}}
```

It ranks a bounded, publisher-and-topic-diverse pool. The optional `scope` accepts `hours` (12, 24, 168 or 720), `source`, `publisher`, `kind`, `topic`, `region`, `coverage`, `language`, and `subject` with the same IDs used by `/api/news`. Omit individual filters for all values. The default is seven days of all coverage. Search `q` and the scope are applied before the archive samples candidate rows. The response echoes `scope` and includes `articles`, `total_candidates`, `personalized`, `basis`, and `updated_at`. Each article includes `recommendation_reasons`. Interests, up to 50 followed source groups/feeds, and up to 30 validated author keys receive preference weights, with smaller freshness, excerpt-availability and engagement signals. A publisher diversity penalty and canonical URL deduplication reduce repetition. This ranking uses the supplied preferences and requires zero model calls. Browser interests stay local. Selected preferences and at most 100 excluded read IDs are submitted per request. Responses are `no-store` and the endpoint is rate limited.

## Author reading permissions

The author workspace is `/contribute.html?article=<id>`. It reuses existing inbox verification at `/api/mail/challenge` and `/api/mail/verify`. Verification by itself sends no digest and creates no newsletter subscription. Its session cookie remains scoped to `/api/mail`.

- `GET /api/mail/contributions/config` reports authentication availability, the current permission statement and version, and the current inbox verification state. It never exposes an owner key.
- `POST /api/mail/contributions` requires a verified session and accepts `article_id`, `author_name`, `body_markdown` (200–30,000 characters and at most 60 KB), `permission_evidence` (30–2,000 characters), `grant_permission: true` and the exact `terms_version`. The article must already be retained and enabled. At most three submissions per mailbox per UTC day are accepted. The response is `201` with a pending ID. No URL is fetched and nothing is published automatically.
- `GET /api/mail/contributions` lists the verified mailbox's 50 latest submissions without bodies. `GET /api/mail/contributions/{id}` returns that mailbox's private submission and review history. Other mailboxes receive `404`.
- `POST /api/mail/contributions/{id}/withdraw` is account-scoped and idempotent. It withdraws the submission and disables the corresponding public reading grant, without affecting a newer approved replacement.
- `GET /api/admin/contributions?state=pending&cursor=<id>` requires the owner bearer token. It returns batches of ten review records, a `next_cursor`, and verified email addresses for permission checks. Bodies are loaded individually through `GET /api/admin/contributions/{id}`.
- `POST /api/admin/contributions/{id}/review` requires the owner token and accepts `action` (`approve`, `reject`, `revoke`), a meaningful review `note`, and `permission_verified: true` for approval. Only pending records can be approved or rejected; only approved records can be revoked. Withdrawn grants cannot be reinstated by replaying approval. Review and withdrawal transitions use database locks and retain versioned permission evidence and action history.

Private responses are `no-store`. Raw Markdown stays in private review records; public HTML is rebuilt through a strict element/link allowlist. Scripts, images, embedded assets, forms, event handlers and styles are removed, with a second allowlist in the browser. The owner key stays in page memory and is cleared on lock. These routes do not create per-user email delivery privileges beyond the existing verified-inbox rules.

`GET /api/trending` analyzes the recent, bounded pool across reporting, developer articles, research and community sources. Counts describe observed matching records, not global popularity. It excludes future-dated records and exact canonical duplicates. The returned `query` is derived from source text so the topic chip opens a searchable phrase. `source_count` gives the number of observed source feeds.

## Build and deliver a brief

Post JSON to `/api/digest` with `edition` (`world` or `personal`), `hours`, and `top_n` (1–10). Both editions accept `topic`, `subject`, `region`, `language`, `coverage`, `sources`, and ordered `pinned_ids`. The coverage setting filters sources for automatic story selection. Explicit pins can include stories outside that scope. A personal edition can also specify `name`, `focus`, free-text `topics`, `persona`, and `style`. The response contains the preview, Markdown, HTML, and delivery metadata. The personal edition requires a configured OpenAI key. The article reader uses this same validated pipeline with one pinned story for its AI brief action.

Add `?stream=true` to receive newline-delimited JSON. Events contain a numbered `stage`, a final `result`, or an `error` with a `status` and optional `retry_after`. Errors emitted after streaming starts are carried in the stream rather than the HTTP status.

Story `summary_basis` is `ai_feed_summary`, `publisher_excerpt`, or `headline_only`. A personalized result also reports synthesis status, the number of AI summaries, and whether final ordering came from the model or from the initial selection. Original titles and links always come from the feed records.

`POST /api/email` requires the owner bearer token and the signed, expiring digest response. The recipient is fixed by server configuration. The `/api/mail` routes verify an inbox before sending a stored preview and accept an explicit opt-in for the daily global edition. `/api/deliver/webhook` requires a verified inbox and accepts supported HTTPS Slack and Teams webhook URLs.

## Health and job routes

`GET /api/health` reports service liveness and configuration. `GET /api/ready` returns `503` if the archive is missing or lacks a fresh feed. Job routes require a configured scheduler token. See [release operations](LAUNCH.md) for setup, quotas, and delivery monitoring.
