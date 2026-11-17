# Reviewed source network

Expanded November 17, 2026 from 191 to 389 source integrations. These are feed/API
integrations, not 389 independent publishers. The catalog currently has 272
publisher-family keys, seven formats and 16 language codes. Related official
Google, Microsoft, Amazon, NVIDIA and Meta feeds share a family for trend counts.
Community and aggregation platforms are grouped conservatively.

## Research and selection

[source-research-2026-11-17.json](source-research-2026-11-17.json) records 297
candidate configurations and point-in-time endpoint checks. Replacements were
found through publisher-declared feed links, including PyTorch, ClickHouse,
Socket and podcast sources. HTTP success alone was insufficient: feeds were
parsed, article hosts and paths checked, and dates inspected. Some candidates
were blocked, malformed, empty, outdated or moved and were not enabled.

The pack adds 198 integrations: 81 technical blogs, 51 release feeds, 30 news
feeds, 21 newsletters, six video channels, five podcasts and four scholarly
feeds/APIs. Twelve established but infrequent primary/practitioner feeds are
included with six-hour checks. A successful fetch of an infrequent feed does
not mean new content exists. The directory exposes this distinction.

Examples include Latent Space, Import AI, Interconnects, Ahead of AI, Hamel
Husain, Lilian Weng, Chip Huyen, Eugene Yan, BAIR, Microsoft Semantic Kernel,
PyTorch, major AI/framework releases, AWS engineering feeds, Grafana, Supabase,
Real Python, Julia Evans, specialist security researchers, regional technology
publications, Practical AI, Darknet Diaries, and Software Engineering Daily.
Existing Medium, Hashnode, DEV, engineering, mainstream reporting, advisories,
papers and status feeds remain available.

The six new YouTube IDs were checked against their actual feed channel names:
3Blue1Brown, Computerphile, Fireship, freeCodeCamp.org, Google for Developers and
Y Combinator. Only supplied titles/descriptions and original links are indexed;
no videos or transcripts are downloaded or rehosted.

Crossref discovery uses reviewed journal ISSNs and public scholarly metadata.
The adapter accepts only complete publisher-supplied publication dates, preserves
day precision and canonical DOI identity, and never copies abstracts. It
serializes requests, spaces them and respects a shared 429 cooldown. This does
not independently establish a paper's accuracy or peer-review outcome.

## Runtime architecture

Core sources remain in `app/sources.py`. New reviewed entries live in
`app/source_catalog.json`. Pack loading performs no network requests and rejects
duplicate IDs/endpoints, non-public URLs, unsupported formats/types and invalid
polling configuration. Pack entries do not create arbitrary public URL fetching.

Scheduled and reader-triggered refreshes select due sources by oldest deadline.
A batch is capped at 128 sources and six per host, with two concurrent fetches
per host. The existing database lease serializes refresh jobs across instances.
Per-source intervals, conditional RSS requests and Retry-After/backoff reduce
unnecessary requests. Five-minute job scheduling is a target, not a timing SLA.
More than one job may be needed to drain a backlog. Source health remains public.

Typical configured intervals are five minutes for advisories/status, ten to
fifteen minutes for reporting, thirty minutes for technical blogs, one hour for
releases/newsletters/podcasts, and longer for journals or infrequent blogs.
Freshness tolerances account for the declared cadence. Directory rows show the
interval, last check, retry and retained-content state.

`brief_feed_checks` stores bounded operational history for seven days: source,
check time, availability, item count, unchanged state, latency and error code.
No user identity or publisher body is stored in this history. The source health
API provides aggregated success counts and up to 50 recent checks.

`classification_version` supports an additive reclassification migration. New
facets cover agents, LLMs, Generative AI, machine learning/MLOps and DevOps.
Bounded technical identifiers from supplied feed text remain searchable even
when absent from the displayed short excerpt. SQL and portable ranking use the
same terms. Existing bookmarks, canonical IDs and reading permissions persist.

Summaries remain extractive or on-demand through the existing AI brief path.
New sources do not trigger a paid model call per article. Full-text reading
continues to require reviewed permission. New newsletter feeds do not subscribe
any person or transmit an email address.

## Adding and auditing sources

Discover only feed links declared on a publisher page:

```powershell
python -m scripts.discover_source_feeds https://publisher.example/blog
```

Review the publisher, format, article hosts, paths, region and content rights,
then prepare a candidate JSON list using the existing catalog shape. Validate
transport, parsing and recent records without activating it:

```powershell
python -m scripts.check_source_pack candidates.json --report source-audit.json
```

After reviewing the report, merge successful entries into the existing pack:

```powershell
python -m scripts.check_source_pack candidates.json --report source-audit.json --promote app/source_catalog.json
```

Promotion validates an atomic merged file and preserves existing entries. It
does not enable failed candidates. For an existing-pack endpoint audit, add
`--recheck-existing`. Use normal tests and release review before deploying.

Existing owner-authenticated source pause/resume remains available. Owner
refresh also accepts `{"source_ids":["reviewed-id"]}` batches of up to 12 IDs for
bootstrap/recovery; it enforces the global lease and never accepts URLs.

## Public tools and verification

- Source directory: format filters, topic coverage, source URL checks, check
  history and OPML download.
- `GET /api/discovery/sources/{id}/health?hours=24`: bounded check history.
- `GET /api/discovery/sources.opml`: enabled RSS feeds only; APIs and sitemaps are
  omitted because they are not reader-compatible RSS subscriptions.
- `GET /api/news?kind=podcast`: podcast discovery; newsletter sources are
  discoverable through directory format filtering and publisher views.

The complete addition pack was ingested into a disposable SQLite archive:
198 attempted, 197 successful at that check, 4,984 retained records, and no
unattempted sources. The largest 128-source batch took 35.6 seconds; total
multi-wave checking took 90.5 seconds. This is a single local integration check,
not a load or availability SLA. One Webrazzi fetch failed after earlier success.
Current production health must be checked independently of this snapshot.

Regression coverage includes bounded/fair scheduling, host caps, backoff,
quiet-source cadence, history retention, authentication, format filters, OPML,
technical-term search parity, scholarly date precision, abstract exclusion,
publisher-family trend counts and safe source discovery.
