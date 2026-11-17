# Informa AI HTTP API

The running app exposes OpenAPI at `/openapi.json` and Swagger UI at `/api/docs`. JSON errors include a `detail` field. API responses include an `X-Request-ID` for log correlation. A `429` may include `Retry-After`.

## Research and intelligence

- `GET /api/intelligence/technologies` lists supported technology IDs and watch triggers. `GET /api/intelligence/technologies/{id}?hours=720` returns grouped archive evidence. The response identifies whether a record came from a registered source, a project repository, or an explicit mention. `POST /api/intelligence/technologies/{id}/ask` accepts a time range, optional question, and output language. The answer cites original-language excerpts. `followed_technologies` on a verified Tech Radar profile boosts matching events in catch-ups.
- `POST /api/intelligence/watch-draft` proposes one structured technology rule without saving it. Review the technology, trigger, and optional version or region, then store it through the existing watch routes. The worker uses archive records and literal filters. A version mention alone does not establish that the version is affected by an advisory.
- `GET /api/intelligence/source-history/{article_id}` returns observed revisions and related archive records. A correction or retraction label requires an explicit notice in the retained title. Publication order represents the retained archive, and shared wording alone does not establish independent confirmation.
- `/api/intelligence/inbox/projects` uses the existing background-monitoring session for project ownership and collaboration. Projects retain a question, archive keywords, and selected sources with notes. Owners can issue single-use collaborator links and revoke access. Shared briefs include the question and current eligible source references, with no project notes. Links expire after 90 days at most and end earlier if access is revoked or the owner’s browser session expires. `POST /api/intelligence/briefs/open` accepts the link token. This route hides cited claims whose saved evidence changed or is unavailable.

- `POST /api/intelligence/research` accepts `{"q":"Kubernetes security","mode":"search","scope":{"hours":168,"topic":"security"}}`. The full archive scope uses the same filters as recommendations. Modes are `search`, `analyze`, `compare`, and `brief`. To analyze a story, submit `{"article_id":"<id>","mode":"analyze"}`. That path uses a fixed analysis prompt and up to 30 days of related coverage.
- `POST /api/intelligence/explain` takes a retained `article_id`, an output language, and `depth` (`simple`, `developer`, or `technical`). It returns short cited claims with exact source quotes and an explicit evidence limit. Thin excerpts, missing credentials, provider errors, and exhausted daily AI budget return a labeled fallback.
- `GET /api/intelligence/events?hours=168&limit=24&topic=all` returns source-linked developments grouped by deterministic headline evidence. `GET /api/intelligence/events/{event_id}` returns the publication/revision timeline. Grouping links coverage; it does not claim that publishers independently confirm identical facts. The hourly intelligence job indexes recent stories and changed feed records in a bounded batch.
- `POST /api/intelligence/catchup` ranks new and revised developments against a validated radar profile, recent delivered versions, time window, and reader perspective. The response includes a server-stored, expiring preview accepted by the existing verified-inbox `POST /api/mail/send` route; existing daily email quotas and anti-abuse controls still apply. Up to three shared, cached publisher-excerpt explanations are prepared per request; remaining items retain their publisher summaries. Event versions are marked seen only after provider acceptance.
- `POST /api/intelligence/converse` accepts a follow-up question and up to eight recent session turns/source IDs. Conversation text is not stored; only the current request's user questions and validated archive source titles influence retrieval. Answer claims use the regular citation validation, and the browser session holds the transcript.
- Verified inbox owners can `GET`, `PUT`, or `DELETE /api/mail/radar`. Preferences are private to the verified inbox, and `PUT` does not subscribe it to email. The browser-only radar preferences are included in the reading-data export/reset controls. Removing the profile deletes its delivered-event history and pending reservations.
- Responses include original-source evidence, source match type, overlapping coverage clusters, index status, and optional cited claims. `retrieval=hybrid` means semantic matches were included. A provider failure, quota limit, or warming index leaves keyword results available. A claim distinguishes reported facts from interpretation. Citation IDs are limited to the supplied excerpt set.
- `POST /api/intelligence/watch` accepts up to six `{"id":"watch-id","query":"Kubernetes security","topic":"all"}` entries in a `watches` array. It checks keyword matches in the past 48 hours and groups overlapping coverage. Browser-only watches track newly observed groups while the Research Desk is open.
- `GET /api/intelligence/inbox` returns the current browser session's watch list, revision, up to 60 retained alerts and an unread count. Explicitly opt in with `POST /api/intelligence/inbox/enable` and `{"watches":[]}` or a list of up to six watches. The server issues an opaque, HttpOnly, same-site cookie and keeps its hash in the archive. Responses are `private, no-store`.
- `PUT /api/intelligence/inbox/watches` replaces the current list with `{"revision":0,"watches":[]}`. A stale revision returns HTTP 409. Changing or removing a watch removes its prior alerts. `POST /api/intelligence/inbox/read` marks the current inbox read. `DELETE /api/intelligence/inbox` revokes the session and deletes its watches and alerts.
- The scheduled intelligence job checks at most 48 due watches per invocation using publisher titles and excerpts. Overlapping article IDs extend existing alerts. Matches are recent publications added after enrollment, and the inbox is available when the reader returns. Browser polling runs once per minute while visible. Feed freshness follows the separate archive refresh schedule. The worker keeps alerts for 14 days and expires sessions after 30 days of browser inactivity. `POST /api/admin/monitoring/check` runs the same monitoring logic with owner authorization.
- `GET /api/intelligence/daily` serves a cached cited edition when available. The optional `source_edition` contains selected publisher evidence from the preceding 24 hours while the cited edition is pending. It is generated from the same cached selection as `GET /api/briefing`.
- The protected `GET /api/jobs/intelligence` uses the existing job secret and a distributed lease. It checks background watches, updates changed vector records in batches of up to 96, and attempts a new cited briefing hourly. Job output reports monitoring, index, and brief health.
- The existing recommendations endpoint accepts an optional list of up to eight retained `saved_ids`. It uses subjects from eligible articles to rank related coverage, with an explanation in the result. The Reading Room only submits them if the reader enables this preference.

### Activation

The hourly Vercel slots run the intelligence check with a shared lease. This provides a fallback when GitHub delays scheduled jobs.

Use the existing owner setup endpoint, `POST /api/admin/setup`, for the additive vector and monitoring tables. Analysis uses the app's existing OpenAI configuration. Set `NEWS_AI_RESEARCH=0` to disable inference for these endpoints. Set `NEWS_AI_VECTORS=1` on the app to enable embeddings. The scheduled GitHub refresh workflow calls the protected intelligence job separately from feed and mail processing. Dispatch it with `intelligence_only=true` to run the intelligence job. The always-on feed and mail worker can also call it every five minutes with `NEWS_AI_WORKER=1`. Background watches and the source briefing use the archive without provider calls.

The semantic index covers the recent 30-day window. Each query scores at most 1,200 recent, eligible vectors after filtering, using the same binary representation on PostgreSQL and SQLite. Older records remain searchable by keyword up to existing archive retention. A cold index warms gradually from diverse sources. A generated answer is never required to show search results.

Set `NEWS_AI_ANALYSIS_MODEL` to route coverage comparisons to a different configured model. `NEWS_AI_ANSWERS_DAILY`, `NEWS_AI_QUERIES_DAILY`, and `NEWS_AI_INDEX_BATCHES_DAILY` cap generation, query embeddings, and archive batches separately. Fixed article analyses and public briefings can be reused. Arbitrary questions and answers are not persisted by the application. The research service uses archived titles and publisher excerpts.

## Discover stories

`GET /api/headlines` returns reviewed developing coverage and a ranked selection of recent articles from enabled reporting feeds. The homepage uses it independently of the Reading Room’s time window and sort.

`GET /api/briefing` returns up to five current publisher records for the Daily briefing view. Optional `hours` ranges from 12 to 168 and defaults to 24. Selection uses a bounded archive sample, includes reporting, official publications, advisories, journals and preprints, and diversifies topics and publishers. It reduces closely matching headline coverage. Each article retains its supplied excerpt, original link and summary basis, plus `coverage_count` and `coverage_publishers` from matching records in the sample. The response includes `total_candidates`, `publishers`, `latest_published_at`, `updated_at` and source `freshness`. Publisher counts describe the observed sample. The endpoint uses a one-minute application cache and a 30-second CDN cache when it has stories. An empty archive returns an empty selection with its source status.

`GET /api/news?hours=168&q=vector+search&sort=relevance&limit=12`

- `hours` accepts `12`, `24`, `168`, `720`, or `2160`. The 90-day window covers retained, previously ingested articles.
- `topic`, `subject`, `source`, `publisher`, `kind`, `region`, `language`, and `coverage` can be combined. `GET /api/sources` returns `topics`, `subjects`, `regions`, `languages`, and `coverage_types` maps, plus provenance, integration type, last successful check, and latest retained publication time for each source. `region` describes the publisher's coverage. Use `coverage=article` for articles and tutorials, `source=medium` for selected Medium feeds, or `subject=cloud` for cloud infrastructure across topics.
- `facets.topics`, `facets.regions`, and `facets.languages` count articles in the active publication window before pagination. Each facet applies the other filters while ignoring its own selection. `source_counts` counts stories by source group while ignoring the `source` selection.
- `sort` accepts `latest`, `oldest`, or `relevance`. Search matches terms in titles, publisher names, feed excerpts, and retained author names and tags. It folds capitalization and Latin accents and tolerates punctuation such as the hyphen in `zero-day`. Relevance gives extra weight to titles with the full phrase. Archive and direct-feed search use the same weights. Relevance without a query uses newest-first order.
- `limit` ranges from 1 to 50. Pass `next_cursor` with the same query, filters, and sort. The cursor keeps the original publication window, returned as `window_ends_at`, for up to 24 hours. Late-arriving stories and edits within that window can still change results.
- `freshness` reports the selected feeds’ last check, last success, and counts, including the selected region. `force=true` reloads the archive from its database. A source record includes `retry_at` while it is waiting for its next eligible check. Publisher requests belong to protected scheduled and owner refresh endpoints.

The two broad DEV streams require a technical title, excerpt, or topic tag. The archive applies the same rule to previously retained posts, so search totals, recommendations, and reading details exclude out-of-scope records.

Reviewed source path and title constraints also apply to retained articles through the additive `source_eligible` field. SCMP Technology uses the publisher's technology feed and requires its technology article paths. Existing out-of-section records stay retained while discovery excludes them.

## Reading and recommendations

`GET /api/articles/{article_id}` returns an enabled, retained article, up to five related articles, a reading notice and `summary`. The summary includes `text`, `basis`, `limited_source` and an array of short extractive `highlights`. `publisher_excerpt` uses supplied excerpt sentences, while `headline_only` has no highlights. An active, owner-approved permission makes `reading` available with sanitized HTML, plain text and attribution. Highlights from that body use `licensed_article_extract` with `limited_source: false`. `also_indexed_by` lists enabled secondary feeds that supplied the same archived ID. Missing or paused-source articles return `404`. Detail responses use `no-store` and check permission on each read. The frontend uses `/?article=<id>#reading-room` for shareable links during the article's archive retention.

Article records may include `author`, `author_url`, `author_key`, `tags`, `original_url`, `discussion_url`, `points`, `comments_count`, and a reviewed `thumbnail_url`. These fields are bounded and sanitized before storage and on read. Images are loaded directly from reviewed hosts with no referrer. `reading_time_basis` distinguishes a publisher-provided article estimate from the excerpt. `reading_access.mode` is `excerpt`, `headline_only`, or `full_text`; full text requires a separate reviewed permission record and cannot be enabled by upstream metadata. List badges can retain their one-minute cache, while reading details always recheck permission. AI briefs continue to use publisher excerpts even when licensed text is available for reading.

Related results come from the last 30 days, using at most 200 archive candidates. Each result's `related_reason` identifies shared headline terms or a matching CVE/GHSA identifier. The additive `coverage` array contains up to five other publisher records that share a CVE/GHSA reference or have high headline overlap in the same language. The articles must be published within 72 hours of each other. Coverage may overlap with `related` and stays linked to each original article. Use `coverage=journal` to find research journal entries or `coverage=release` for official release feeds. The journal label identifies the publishing venue.

`GET /api/authors?q=writer&limit=80` returns bounded, observed author identities from the recent discovery sample. API profile URLs identify authors when supplied; RSS names without profiles are scoped to their source feed, preventing namesakes from being merged. The returned `id` can be used in recommendations. This is not an exhaustive directory of either external platform.

`POST /api/recommendations` accepts a JSON object:

```json
{"topics":["software","research"],"subjects":["cloud","open-source"],"sources":["dev","medium-codex"],"authors":[],"exclude_ids":[],"q":"Kubernetes","limit":24,"scope":{"hours":168,"coverage":"article"}}
```

It ranks a bounded, publisher-and-topic-diverse pool. The optional `scope` accepts `hours` (12, 24, 168, 720 or 2160), `source`, `publisher`, `kind`, `topic`, `region`, `coverage`, `language`, and `subject` with the same IDs used by `/api/news`. Omit individual filters for all values. The default is seven days of all coverage. Search and scope narrow the archive before sampling. Within each publisher and topic, search relevance, followed authors, and preferred subjects can keep an older matching article in the sample. The response echoes `scope` and includes `articles`, `total_candidates`, `personalized`, `basis`, and `updated_at`. Each article includes `recommendation_reasons`. Interests, up to 50 followed source groups or feeds, and up to 30 validated author keys receive preference weights, with smaller freshness, excerpt-availability and engagement signals. Publisher diversity and canonical URL deduplication reduce repetition. Browser interests stay local. Selected preferences and at most 100 excluded read IDs are submitted per request. Responses are `no-store` and the endpoint is rate limited.

## Author reading permissions

The author workspace is `/contribute.html?article=<id>`. It reuses existing inbox verification at `/api/mail/challenge` and `/api/mail/verify`. Verification by itself sends no digest and creates no newsletter subscription. Its session cookie remains scoped to `/api/mail`.

- `GET /api/mail/contributions/config` reports authentication availability, the current permission statement and version, and the current inbox verification state. It never exposes an owner key.
- `POST /api/mail/contributions` requires a verified session and accepts `article_id`, `author_name`, `body_markdown` (200–30,000 characters and at most 60 KB), `permission_evidence` (30–2,000 characters), `grant_permission: true` and the exact `terms_version`. The article must already be retained and enabled. At most three submissions per mailbox per UTC day are accepted. The response is `201` with a pending ID. No URL is fetched and nothing is published automatically.
- `GET /api/mail/contributions` lists the verified mailbox's 50 latest submissions without bodies. `GET /api/mail/contributions/{id}` returns that mailbox's private submission and review history. Other mailboxes receive `404`.
- `POST /api/mail/contributions/{id}/withdraw` is account-scoped and idempotent. It withdraws the submission and disables the corresponding public reading grant, without affecting a newer approved replacement.
- `GET /api/admin/contributions?state=pending&cursor=<id>` requires the owner bearer token. It returns batches of ten review records, a `next_cursor`, and verified email addresses for permission checks. Bodies are loaded individually through `GET /api/admin/contributions/{id}`.
- `POST /api/admin/contributions/{id}/review` requires the owner token and accepts `action` (`approve`, `reject`, `revoke`), a meaningful review `note`, and `permission_verified: true` for approval. Only pending records can be approved or rejected; only approved records can be revoked. Withdrawn grants cannot be reinstated by replaying approval. Review and withdrawal transitions use database locks and retain versioned permission evidence and action history.

Private responses are `no-store`. Raw Markdown stays in private review records; public HTML is rebuilt through a strict element/link allowlist. Scripts, images, embedded assets, forms, event handlers and styles are removed, with a second allowlist in the browser. The owner key stays in page memory and is cleared on lock. These routes do not create per-user email delivery privileges beyond the existing verified-inbox rules.

`GET /api/trending` analyzes a bounded sample from the last 48 hours across reporting, developer articles, research and community sources. It excludes future-dated records and canonical duplicates. Trends use recent mentions, a shared advisory identifier, or tags supplied by at least three source groups. `basis` identifies the signal, `source_count` reports distinct publisher families, and `query` opens the matching archive search. `recent_source_count` and `previous_source_count` compare two equal publication-time windows. `momentum=rising` requires at least three recent publishers, two more than the previous period, and at least 50% growth.

## Build and deliver a brief

Post JSON to `/api/digest` with `edition` (`world` or `personal`), `hours`, and `top_n` (1–10). Both editions accept `topic`, `subject`, `region`, `language`, `coverage`, `sources`, and ordered `pinned_ids`. The coverage setting filters sources for automatic story selection. Explicit pins can include stories outside that scope. A personal edition can also specify `name`, `focus`, free-text `topics`, `persona`, and `style`. The response contains the preview, Markdown, HTML, and delivery metadata. The personal edition requires a configured OpenAI key. The article reader uses this same validated pipeline with one pinned story for its AI brief action.

Add `?stream=true` to receive newline-delimited JSON. Events contain a numbered `stage`, a final `result`, or an `error` with a `status` and optional `retry_after`. Errors emitted after streaming starts are carried in the stream rather than the HTTP status.

Story `summary_basis` is `ai_feed_summary`, `publisher_excerpt`, or `headline_only`. A personalized result also reports synthesis status, the number of AI summaries, and whether final ordering came from the model or from the initial selection. Original titles and links always come from the feed records.

`POST /api/email` requires the owner bearer token and the signed, expiring digest response. The recipient is fixed by server configuration. The `/api/mail` routes verify an inbox before sending a stored preview and accept an explicit opt-in for the daily global edition. `/api/deliver/webhook` requires a verified inbox and accepts supported HTTPS Slack and Teams webhook URLs.

`GET /api/mail/config` also reports `remaining_today` for the verified inbox, with a three-brief UTC daily limit. `GET /api/mail/delivery/{preview_id}` returns that inbox's delivery outcome, update timestamp, remaining allowance and whether provider webhook tracking is configured. It remains available after the preview expires, for the delivery record's 30-day retention. Another inbox receives 404 and a signed-out reader receives 401. Both responses use private, no-store caching and omit provider IDs and recipient addresses from receipts.

Signed Resend events correlate `data.email_id` with the recorded provider ID. Delivered, delayed, failed, bounced and suppressed outcomes survive webhook replays and events that arrive before the send response. A delayed event cannot replace a terminal outcome. Bounces, complaints and suppressions pause further mail to that inbox. Gmail, SMTP and Postmark report provider acceptance through this receipt endpoint. Resend retries transient transport failures once with the identical payload and idempotency key. Ambiguous attempts retain their quota reservation and cannot initiate a second send of the same preview.

## Health and job routes

`GET /api/health` reports service liveness and configuration. `GET /api/ready` returns `503` if the archive is missing or lacks a fresh feed. Job routes require a configured scheduler token. See [release operations](LAUNCH.md) for setup, quotas, and delivery monitoring.

## Coverage monitoring and priority signals

The reviewed source network is documented in [SOURCE-NETWORK.md](SOURCE-NETWORK.md).
Source records include `format`, `refresh_minutes`, `publisher_family`, `collection`,
`reviewed_at`, `next_check_at` and `content_status`. Feed freshness accounts for
the declared polling interval and measures successful synchronization, not new
publication activity. `GET /api/discovery/sources/{id}/health?hours=24` exposes
up to seven days of operational history. `GET /api/discovery/sources.opml`
exports enabled RSS feeds. Owner-authenticated `POST /api/admin/refresh` accepts
an optional `source_ids` JSON list of up to 12 reviewed IDs.

- `GET /api/signals`: publisher-diverse material developments from 24 hours with explicit selection reasons; not independently verified alerts.
- `GET /api/discovery/coverage`: topic story counts, source health and bounded ingestion diagnostics. Topic `gap` is `no_sources`, `checks_overdue`, `no_recent_stories`, or null. `attention` separates failed, overdue and quiet sources. `regions` reports enabled integration counts, current checks and conservative publisher-family counts.
- `GET /api/discovery/check?url=<publisher HTTPS URL>`: archive and source-health lookup, including community original links. Never fetches the submitted URL.

See [coverage investigation](COVERAGE-REPAIR.md) for discovery boundaries and verification.

`GET /api/jobs/refresh` uses adaptive per-source cadence by default. It returns
`mode: "adaptive"`, `checked`, `healthy` and `remaining` for a bounded batch.
The database lease prevents overlapping workers; publisher backoff is respected.
`FEED_REFRESH_MODE=daily` retains the optional morning sweep. Job authorization
is required in either mode; public readers never submit upstream feed URLs.
