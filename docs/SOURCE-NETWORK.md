# Reviewed source network

Expanded November 17, 2026 from 191 to 477 source integrations. These are feed/API
integrations, not 477 independent publishers. The catalog currently has 326
publisher-family keys, seven formats and 18 language codes. Related official
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

The second research pass examined 129 additional candidates and rechecked 18
recovered URLs. It enabled 88 integrations with eligible publications in the
preceding 90 days: 40 blogs, seven regional news feeds, seven research feeds,
25 project release feeds, seven video channels, one newsletter and one podcast.
The [validation evidence](research/source-validation-2026-11-17.json) records
each check, parsed/recent counts, sample original links, failures and approved IDs.
Checks are point-in-time evidence, not a publisher availability guarantee.

Additions include Modal, AMD ROCm, fast.ai, Nicholas Carlini, Sander Dieleman,
matklad, Hillel Wayne, Charity Majors, Will Larson, DuckDB, ScyllaDB, Tailscale,
Fly.io, Temporal, Confluent, Google Project Zero, OpenSSL, Wiz, Rapid7, Huntress,
Securelist, Qiita, NAVER D2, Kakao, LY Corporation, VnExpress, Sekurak, TechMoran,
Zoomit, The TWIML AI Podcast, and official Codex, Claude Code, Gemini CLI,
Playwright, DSPy, Langfuse and Apache project releases. New arXiv subject feeds
cover machine learning, language, vision, robotics, algorithms and databases.

Several endpoints were recovered from publisher-declared feed links or observed
canonical redirects. Unavailable endpoints and dormant feeds were left out of
this addition. A podcast URL that returned another show's feed was rejected.
Broad business/personal feeds use the technology relevance filter. The catalog
uses publisher-supplied language metadata; it does not translate every article.

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

The November 19 additions bring the enabled catalog to 513 sources. They cover
Francophone and East African technology, Thai and Philippine news, Spanish-language
WIRED, EU digital policy, space, medical technology, and Gulf tech investment.
OpenAI and Vercel add first-party service status. Latitude Media contributes
technology-relevant videos from its official channel. WIRED en Español, The Circuit,
and Latitude Media are indexed as headlines with source links. The Circuit and
Latitude Media use the technology filter.

Core sources remain in `app/sources.py`. New reviewed entries live in
`app/source_catalog.json`. Pack loading performs no network requests and rejects
duplicate IDs/endpoints, non-public URLs, unsupported formats/types and invalid
polling configuration. Pack entries do not create arbitrary public URL fetching.

Vercel Schedules runs publisher sweeps at 08:00 and 20:00 IST, with a
45-minute window. Between them, GitHub Actions starts light checks at 02:00 and
14:00 IST that cover only the busiest newsrooms, advisories and status pages
(`run=priority`, two-hour window), so breaking news waits at most about six hours. The worker checks up to two feeds concurrently per host
and fourteen overall. Manual recovery batches check up to 64 sources and twelve
feeds per host. A shared lease prevents overlaps and each source can be claimed once
in each sweep. Conditional RSS requests and publisher backoff reduce traffic.
Readers reload the archive without contacting publishers.

The catalog's cadence values prioritize checks within a sweep. Directory rows
show the public schedule, last check, retry and retained-content state. The
public ingestion report tracks sweep progress, deferred checks and outstanding
claims. Subscriber delivery times are set separately.

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

Follow the [English-language source policy](ENGLISH-SOURCE-POLICY.md) when reviewing candidates.

Discover only feed links declared on a publisher page:

```powershell
python -m scripts.discover_source_feeds https://publisher.example/blog
python -m scripts.discover_source_feeds --seeds app/discovery_seeds.json --report discovered-feeds.json
```

Review the publisher, format, article hosts, paths, region and content rights.
Use English-language feeds for new sources, including English editions from
publishers that serve multiple languages. Existing multilingual sources remain
available. Prepare a candidate JSON list using the existing catalog shape and
validate transport, parsing and recent records without activating it:

```powershell
python -m scripts.check_source_pack candidates.json --report source-audit.json
```

After reviewing the report, merge successful entries into the existing pack:

```powershell
python -m scripts.check_source_pack candidates.json --report source-audit.json --promote app/source_catalog.json
```

Promotion requires at least 80% verified English in the sampled recent entries
and zero detected non-English entries. Ambiguous samples count against the 80%
threshold. New feeds accept only verified English stories during ingestion.
Promotion validates an atomic merged file and preserves existing entries. It
does not enable failed candidates. For an existing-pack endpoint audit, add
`--recheck-existing`. Use normal tests and release review before deploying.

The manually dispatched `source-review.yml` workflow checks reviewed seed pages
and new additions and retains JSON evidence as a 30-day Actions artifact.
Publisher identity, permitted usage, content relevance and article hosts
require review before enabling a discovered URL. The scheduled sweeps maintain
the seven-day health history for existing sources.

Existing owner-authenticated source pause/resume remains available. Owner
refresh also accepts `{"source_ids":["reviewed-id"]}` batches of up to 12 IDs for
bootstrap or recovery during an open sweep. It uses the same lease and publisher
claims as the scheduler and accepts only catalog IDs.

## Public tools and verification

- Source directory: format filters, topic coverage, source URL checks, check
  history and OPML download.
- Coverage monitoring distinguishes missing source coverage, unsuccessful or
  overdue checks, and topics without retained publications in the past 24 hours.
  Regional counts describe configured coverage, not exhaustive international reporting.
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

The second-pass addition was also ingested into a separate disposable SQLite
archive: 88 attempted, 87 successful, 3,666 retained records, 28.9 seconds across
three host-bounded batches. VnExpress had a transport failure after its earlier
successful check and remains visible for retry. This exercise made no changes
to the production archive or subscriber mailboxes. Full regression verification
passed 244 backend tests (34 environment-gated tests skipped) and 34 client tests.

## Adding sources: candidate packs

New sources arrive as a reviewed candidate pack under `docs/research/`, never straight into the catalog. `scripts/source_candidates_2026_11_21.py` builds the November 21, 2026 pack (190 English candidates: AI labs and research, independent AI writing, arXiv categories, 54 GitHub release feeds for agent frameworks, LLM tooling, runtimes and infrastructure, company engineering blogs, documentation changelogs, Medium and DEV topic feeds, security research and news, DevOps, hardware, robotics, quantum, XR, startups, regional English outlets, podcasts and YouTube channels). The builder refuses any id or URL already in the catalog.

Run **Validate candidate sources** from the Actions tab (it needs no secrets and makes read-only feed requests from GitHub's runners). It runs `scripts.check_source_pack` with `--promote`, prints one line per candidate (status, English verification, recent entries, error) and a `PROMOTE_IDS=` line, writes a table to the job summary, and keeps the report as an artifact. Then add the approved sources locally:

```sh
uv run python -m scripts.promote_sources docs/research/source-candidates-2026-11-21.json --ids <PROMOTE_IDS>
```

Promotion appends only the listed candidates with `reviewed_at` and `require_english`, never changes existing entries, and validates the merged catalog with the application's loader. Dormant, unavailable, non-English or misconfigured candidates stay out until they are fixed and rechecked. Sweeps pick up promoted sources at the next 08:00 or 20:00 IST run; the follow-up job finishes any sources the Vercel batch does not reach.

### November 21, 2026 results

Validation run 44917117113 checked all 190 candidates: 97 were active and English-verified, 40 were active but failed the original English check, 30 had no entries in 90 days and 23 were unreachable. The English check then changed: release, video and podcast feeds rely on their reviewed language, and article feeds pass at 60% detected English with at most 10% confidently foreign. The 97 were promoted with six arXiv categories (empty only because arXiv publishes no RSS on weekends). Run 44917920438 rechecked 50 (the 40, two moved repositories and eight corrected URLs): 33 passed and were promoted. Ten more were active, well-known English publishers or projects that still fell short of the detector threshold on code-heavy or very short titles (Jane Street, LLVM, Slashdot, Node Weekly, Data Engineering Weekly, watchTowr Labs, AI as Normal Technology, Medium Kubernetes, the MCP TypeScript SDK and Unsloth); they were promoted after manual review, article feeds with `require_english` so any confidently foreign item is still dropped. Seven corrected URLs remained unreachable and stay out, as do the dormant and blocked candidates. Enabled sources: 518 before, 664 after.

### Source policy: quiet is not broken

Informa AI is a broad directory of reliable, mostly English technology sources. It shows headlines, short excerpts or summaries and direct links to the original publisher; it does not reproduce articles. A source is judged on whether its feed works, not on how often it publishes:

- **Active**: the feed was fetched and parsed and has entries from the last 90 days.
- **Quiet**: the feed was fetched and parsed but has no entries from the last 90 days. Quiet feeds are promoted and kept; their language is judged on whatever entries they have, or on the review when they have none. In production the same distinction appears as `content_status` (`recent`, `quiet`, `no_retained_content`), which never marks a source as failed.
- **Unavailable**: the feed could not be fetched or parsed (`feed_not_found`, `access_denied`, `invalid_feed`, repeated `fetch_failed`, `no_eligible_entries`). Only these are rejected or paused, with a recorded reason.

Fresh daily news comes from ranking and the reader's time window, not from removing quieter publishers. On November 21, 2026 the 21 quiet candidates from run 44917117113 (for example Andrej Karpathy's blog, The Gradient, Stanford AI Lab, V8, AutoGen, Aider, Keras and Nuclei releases) were promoted on this basis; Google's Gemini cookbook release feed was left out because it is documentation, not news. Enabled sources: 685.

## Second wave (November 21, 2026)

`scripts/source_candidates_2026_11_21b.py` builds `docs/research/source-candidates-2026-11-21b.json`: 184 further English candidates chosen from the gaps that remained after the first wave. They include cloud and platform changelogs, service status pages (Anthropic, AWS Health, Fastly, Slack, Bitbucket), national CERT and vulnerability feeds (Canadian Centre for Cyber Security, HKCERT, Ubuntu security notices, Exploit-DB), security research (Citizen Lab, Sophos, Tenable, Objective-See, GitHub Security Lab), AI research and independent writing (LMSYS, Epoch AI, Hazy Research, Stanford HAI, Communications of the ACM, smol.ai AI News, Zvi Mowshowitz, Exponential View, TLDR AI), developer podcasts, company engineering blogs (DoorDash, Yelp, Figma, Canva, Swiggy, Flipkart, Mercari, Gojek, Meesho), electronics and hardware trade press, telecoms, regional English outlets (Techpoint Africa, Techweez, MyBroadband, MENAbytes, TechJuice, DailySocial, The Bridge, IT World Canada, The Hindu, Gadgets 360) and 76 more GitHub release feeds for agent frameworks, LLM serving and tooling, data platforms and cloud-native infrastructure. The builder refuses any id or URL that is already in the catalog or was proposed in the first wave, so failed candidates are not silently retried.

Validate the wave with **Validate candidate sources**, setting the pack input to `docs/research/source-candidates-2026-11-21b.json`, then promote the approved ids with `scripts.promote_sources` exactly as for the first wave.

The coverage report (`GET /api/discovery/coverage`) now also returns `subjects`: stories per subject over seven days, with `thin` (fewer than five) and `no_recent_stories` flags, repeated under `attention.subjects`. The Source Directory shows them as "Subjects this week" so thin subjects point to where new sources are needed. A thin subject is a prompt for source review, never a reason to drop an existing source.

Validation run 44932653878 checked all 184 second-wave candidates from GitHub's runners: 124 were active, 25 were quiet (reachable and parseable, nothing in 90 days) and 35 were unavailable (blocked, moved or not a feed, for example Gizmodo, Windows Central, The Register's security feed, Epoch AI, LMSYS and the Anthropic and Fastly status pages). The run approved 136. Eleven more were active, English publishers or projects whose short or code-heavy titles fell under the detector threshold (Ubuntu security notices, Exploit-DB, Honeycomb, Console.dev, and the Claude Agent SDK, Consul, AutoGPT, Streamlit, Kong, Delta Lake and Graphiti release feeds); they were promoted after manual review, article feeds with `require_english`. Toss Tech and HKCERT were left out because their feeds are not reliably English, and the Gradient Dissent podcast feed is dormant. Enabled sources: 685 before, 832 after. Unavailable candidates stay out until a working endpoint is found and rechecked.

## Curiosity engineering feeds (2026-11-21)

Two engineering blogs were added for Curiosity Cards discovery after their feeds were checked in a browser: Engineering@Microsoft (`engineering-at-microsoft`, `https://devblogs.microsoft.com/engineering-at-microsoft/feed/`) and Palo Alto Networks Engineering Blogs (`paloalto-engineering`, the community board RSS on `live.paloaltonetworks.com`). Both are English, kind `engineering`, coverage `publisher`, and are fetched in the existing 08:00 and 20:00 IST sweeps. That brings the catalog to 834 enabled sources. Uber Engineering stays disabled as a feed; its articles appear only as reviewed Curiosity seeds.

## Release feed filtering

Release feeds publish stable versions only. Alpha, beta, release-candidate, nightly, canary and dev builds are skipped at ingestion so they do not crowd out real releases. A feed that only posted prereleases still counts as working, not broken. CMS footers such as "The post … appeared first on …" and "Continue reading" links are stripped from excerpts when stored and when displayed.

## Game engineering sources (2026-11-22)

Six feeds were checked in a browser and added for Curiosity Cards discovery, in the collection `Game engineering`: Unreal Engine Blog (`unreal-engine-blog`), Godot Engine Blog (`godot-engine-blog`, articles only), AMD GPUOpen (`amd-gpuopen`), Factorio Friday Facts (`factorio-blog`), Aras Pranckevičius (`aras-p`) and the Box2D Blog (`box2d-blog`). The candidate pack is `docs/research/source-candidates-2026-11-22-game-engineering.json`; run **Validate candidate sources** on it to recheck from GitHub's runners. Riot Games, Rockstar, Roblox, GDC Vault and SIGGRAPH course pages publish no usable feed, so their best engineering pieces are reviewed Curiosity classics with checked links instead. Rockstar publishes little engineering detail; its card is a first-party SIGGRAPH talk, and the GTA V graphics study is labelled as independent analysis.
