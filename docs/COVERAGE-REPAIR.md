# Coverage investigation and repair

Investigated November 17, 2026 against production search and live publisher endpoints.
No reported article was inserted manually.

| Reported link | Confirmed cause | Pipeline correction |
| --- | --- | --- |
| VentureBeat security investigation | Publisher absent from registry; public feed and declared news sitemap returned HTTP 429. Other indexed publishers covered the event, but the default 12-hour view hid older reporting. | Register monitored publisher endpoints, integrate Google Threat Intelligence, show priority signals over 24 hours and offer explicit 90-day search. |
| BBC Landeed / Fractal Analytics | No archive match; absent from checked Technology, Business, India and general feeds, but present in BBC's news sitemap. | Technology-filtered discovery across three reviewed BBC news sitemap partitions. |
| TechCrunch Bharat Semi | Article predates the default 12-hour view. Main RSS snapshot had only 20 stories; Startups section still contained it. Production ownership by the original main feed indicates prior archive capture; an exact pre-change archive lookup was not performed. | Five category feeds with canonical deduplication and feed provenance. |
| X link to Moneycontrol Nvidia / India article | Publisher absent; November 14 article omitted from shallow technology feed and current news sitemap, but still linked in the IT section. | RSS, news sitemap and robots-aware section metadata discovery. |

## Implementation

The registry grows from 168 to 191 integrations. New security sources include
Google Threat Intelligence, Google Security, Microsoft Security, AWS Security,
Cisco Talos, SentinelLABS, Unit 42, ESET and UK NCSC. Hardware/research additions
include Tom's Hardware, MIT AI and IEEE Robotics. Parsed-entry validation was
used rather than HTTP status alone. A transparent InformaAI crawler user agent
replaces the browser-like header. HTTP permalinks are upgraded only on reviewed
publisher hosts; article pages are not fetched by that normalization.

News sitemap discovery accepts publisher headlines and publication dates, never
lastmod as publication time. Child indexes are restricted to reviewed same-host
paths. XML entities/document types and oversized downloads are rejected. No
article body is copied. The section metadata connector reads robots rules,
follows at most eight reviewed same-host paths and skips archived URLs. It stores
headline, date, author and at most 400 characters of public description metadata.
JSON parsing safely tolerates literal newlines inside publisher string values.

Security advisory classification takes precedence over broad research-kind
classification. Existing canonical IDs deduplicate RSS, section, sitemap and
metadata sightings while preserving provenance. Independent reports remain
addressable. Related-story matches do not establish factual consensus.

`GET /api/signals` selects recent material developments using explicit security,
outage and company-change rules, publisher diversity and duplicate detection.
It includes primary advisories and provides selection reasons. These are
priority signals, not independently verified breaking-news alerts.

The reader preserves bounded safe references from feed excerpts. Existing
extractive highlights and AI brief creation retain attribution and their
available-text basis. Full-text reading requires reviewed permission; missing
technical details and implications are not invented.

`GET /api/discovery/check?url=...` checks the 90-day archive, canonical aliases,
community original links and source health without fetching submitted URLs.
A link cited in another story does not falsely count as an indexed article.
`GET /api/discovery/coverage` reports topic counts, publisher groups, freshness,
retained records, retries and parsed/rejected-entry diagnostics. The source
directory exposes coverage and link checks. Reader search can explicitly expand
to 90 days. Priority signals open the existing reader.

GitHub scheduling changes from 15 minutes to a five-minute target; GitHub can
delay scheduled runs, so this is not a guaranteed real-time SLA. Reader stale
checks use five minutes. Existing database leases, backoff and cooldowns prevent
duplicate refreshes. Hourly Vercel jobs remain as fallback. The additive
`brief_feed_diagnostics` table preserves existing archive and delivery records.

## Verification boundaries

Regression tests cover sitemap host/path constraints, dates, XML entities,
canonical deduplication, provenance, HTTP link upgrades, safe references,
robots rules, metadata skipping, URL lookup, topic counts and signal eligibility.
Client tests exercise coverage-check success/error and safe text rendering.
PostgreSQL migration tests include the diagnostics table. Isolated live
discovery recovered the BBC, TechCrunch and Moneycontrol records through normal
ingestion and loaded Google's primary security feed. VentureBeat remains subject
to publisher availability and its failure is exposed. Healthy feeds are not
evidence of exhaustive coverage.
