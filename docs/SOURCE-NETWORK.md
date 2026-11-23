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
(`run=priority`, open until 30 minutes before the next sweep), so breaking news waits at most about six hours. The worker checks up to two feeds concurrently per host
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

### Source policy: publishers that deny access are not fetched

A publisher that refuses automated access (HTTP 401 or 403, recorded as `access_denied`) is not part of the news feed. The candidate validator already reports such feeds as `unavailable`, so they are never promoted. Because GitHub's runners and Vercel's servers are blocked differently, production applies the same rule (`access_denied` in `app/ingestion.py`): a feed that has never worked stops being fetched after its first refusal, and a feed that has worked gets 14 days to recover from a passing block. It then appears as paused in the source catalog and leaves the "feeds up to date" count, and it is removed from the catalog at the next review. Rate limits (HTTP 429), timeouts and publisher outages are not refusals: those feeds stay, back off and are retried in every sweep.

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

## Global expansion and feed health (2026-11-22)

Twelve feeds were opened in a browser and promoted, from `docs/research/source-candidates-2026-11-22-global.json`: Game Developer, GamesIndustry.biz, 80 Level, Graphics Programming Weekly, Josh W. Comeau, Overreacted, TkDodo, Addy Osmani, CSS-Tricks, PostHog, the Vespa blog and the DoorDash blog. The same pack holds 24 more candidates that have not been opened yet. They come from mid-sized companies and independent publishers worldwide: Klarna, trivago, JioHotstar, Dream11, PhonePe, Cookpad, Airtable, Snowflake, MotherDuck, Dagster, TigerBeetle, Turso, Railway, Replit, Plausible, High Scalability, LanceDB, Anyscale, Tailwind, Vite, Next.js, SemiWiki, Unity and Digital Foundry. To validate them, run **Validate candidate sources** on the pack, then promote the `PROMOTE_IDS` it prints. Candidates that an earlier pack had already tried and rejected were left out. `app/discovery_seeds.json` has 66 publisher pages, so **Review publisher discovery and source health** can find more publisher-declared feeds. It reads only each page's `<link rel="alternate">` tags and never adds a source on its own.

Every source now carries a `health` value, set in `source_health` in `app/ingestion.py`:

- `active`: the feed works and has new stories.
- `quiet`: the feed works but has nothing new for 30 days, or nothing retained at all. Silence is never a failure.
- `temporarily_unavailable`: the feed failed, but succeeded within the last 14 days, or failed with a transient error.
- `broken`: there has been no success for 30 days, or the feed failed with a lasting error (missing feed, access denied, DNS, TLS or unreadable response) and has not worked for 14 days.
- `pending` or `paused`.

The Sources page has a Feed health filter and badge. Source monitoring counts the temporarily unavailable and broken feeds.

Validation run #5 (22 November) rechecked `source-candidates-2026-11-21b.json`. Five feeds passed with English confirmed and were promoted: Electronics Weekly, Gizmodo, Don't Worry About the Vase (Zvi), The Chip Letter and THE BRIDGE (English edition). HKCERT and Toss Tech work but did not pass the English check. The Gradient Dissent podcast is quiet and also did not pass the English check, so it was not promoted. The workflow now checks `source-candidates-2026-11-22-global.json` by default.

Validation run #6 (22 November) checked `source-candidates-2026-11-22-global.json`. Eighteen feeds passed with English confirmed and were promoted. Thirteen are active: Tailwind CSS, TigerBeetle, Snowflake Engineering, MotherDuck, Next.js, Dagster, JioHotstar Tech, Railway, Airtable Engineering, trivago tech, SemiWiki, Unity and Plausible. Five are quiet, which means they work but have posted nothing recently: Cookpad Source Diving, Dream11 Engineering, High Scalability, Klarna Engineering and Vite. Six were unavailable and were not added: Anyscale and Digital Foundry (no valid feed at the listed address), LanceDB and Replit (could not be fetched), PhonePe and Turso (feed not found). The catalog now has 875 enabled sources.

## Agentic AI and AI-native engineering in Curiosity Cards (2026-11-23)

Curiosity Cards has two new themes, **AI agents** (multi-agent systems, orchestration, tool calling and MCP, context and memory, evals, sandboxing, prompt injection) and **AI-native engineering** (coding agents, AI-generated tests, migrations, code review and the "software factory"). Both rank a little higher among fresh feed articles. There are 23 new reviewed classics, each opened in a browser before it was written up. They come from Cognition, Manus, Simon Willison, Hamel Husain, Anthropic (MCP, code execution with MCP, Claude Code sandboxing), OpenAI's agents guide, Slack (long-running multi-agent security investigations, agentic E2E testing, multi-cloud LLM serving), Stripe Minions, Spotify Honk, Google, Meta ACH, Airbnb, Shopify Roast, Discord, Figma, Stripe DocDB, Pinterest, vLLM and ByteDance Monolith. Reviewed classics can carry a `question`, the engineering question the piece answers, which is shown and searchable on the card. Feed items never get a generated question. The discovery seeds now include 88 publisher pages, adding agent tooling, AI labs and fintech engineering blogs, for the **Review publisher discovery and source health** workflow.

Validation run #7 (23 November) checked `source-candidates-2026-11-23-discovered.json`, which was built from publisher discovery run #3. Fourteen feeds passed with English confirmed and were promoted:

- **Active (13):** Remix, Arize AI, Mistral AI News, Eurogamer Tech (Digital Foundry), E2B, Stripe Dot Dev Blog, Tinybird, Zed, Materialize, PhonePe Tech, Linear Now, Encore and Netlify.
- **Quiet (1):** Shreya Shankar.

The Syntax podcast feed could not be fetched and was not added. The publisher review workflow now prints discovered feeds on its run page.

Validation run #8 (23 November) checked `source-candidates-2026-11-23-round1.json`, 114 candidates covering company engineering blogs, regional English press, AI tooling, security, chips and independent engineers. Fifty-seven feeds passed with English confirmed and were promoted:

- **Active (37):** Engineer's Codex, Shrivu Shankar, Transactional (Alex Miller), CircleCI, Django, EE Times Asia, Ruby on Rails, SANS Internet Storm Center, SitePoint, InfluxData, SingleStore, Duolingo, Murat Demirbas, O'Reilly Radar, Allegro Tech, Data Science at Microsoft, All Things Distributed, Coding Horror, Myntra Engineering, Strava Engineering, Sean Goedecke, Twilio, Drew Breunig, HelloFresh Tech, ING Tech, Whatnot Engineering, Daniel Lemire, TechTrends Kenya, Marc Brooker, monday.com Engineering, Philipp Schmid, Teads Engineering, The Hindu BusinessLine Info-Tech, Tech World with Milan, Angular, Val Town and Wix Engineering.
- **Quiet (20):** Adevinta, Answer.AI, ASOS Tech, Back Market, BBC Product & Technology, Bumble Tech, Disney Streaming, fasterthanli.me, Guardian Engineering, Joel on Software, Miro Engineering, OLX Engineering, Riskified, Square Developer, Squarespace Engineering, Tokopedia, Traveloka, TrendForce, Udemy Engineering and Vue.js.

Ten working feeds were held back because their headlines could not be confirmed as English (mostly short or code-heavy titles): Maarten Grootendorst, Capital One Tech, Mitchell Hashimoto, Scattered Thoughts, Zig News, System Design One, Aphyr, Modular, Delivery Hero and Nikita Prokopov. Forty-seven were unavailable. Sixteen of these, mostly Medium publications, were rate limited during the run and can be retried in a later pack. The others returned no feed, denied access or could not be fetched.

## Vercel Active CPU (2026-11-23)

Vercel paused the project on 23 November until 23 December after it exceeded the Hobby plan's Fluid Active CPU allowance. Usage rose from a minute or two a day to 25–35 minutes a day from 15 November. GitHub's five-minute schedule called the morning-mail, mail-health and intelligence endpoints about 860 times a day, and each intelligence call re-ran monitoring, indexing and the brief. That schedule is now a three-hourly mail backup only. Vercel's hourly intelligence crons already release due briefs and update the index, and intelligence runs from GitHub only on manual dispatch.


## Round two (2026-11-24)

Validation run #9 checked `source-candidates-2026-11-24-round2.json`, which has 156 candidates. Most are GitHub release feeds of widely used languages, frameworks, databases, cloud-native, AI and security projects. The rest are security research, engineering writers, developer platforms and regional press. 130 passed with English confirmed and were promoted (102 active, 28 quiet). The catalog now has 1,072 enabled sources.

- **New blogs and news:** Databricks, Atlassian Engineering, Percona, Crunchy Data, Datadog Security Labs, DevClass, iTWire, ETTelecom, The Information, The Korea Herald Tech, Python Insider, SoundCloud Backstage, Eli Bendersky, Ken Shirriff, Xe Iaso, Drew DeVault, Jessie Frazelle, Russ Cox, Brandur Leach, Bartosz Ciechanowski and Without Boats.
- **New release feeds (109):** among them Node.js, Kotlin, React Native, Prisma, Hono, Fastify, Express, SvelteKit, webpack, Rollup, esbuild, SWC, Nx, pnpm, Turborepo, CockroachDB, TiDB, TiKV, Vitess, Neon, TimescaleDB, Redpanda, Doris, RisingWave, SurrealDB, Meilisearch, Typesense, Sentry, Grafana Tempo/Mimir/k6, KEDA, Knative, Crossplane, OPA, Harbor, Rancher, Karpenter, Tailscale, workerd, Hugging Face Hub and Tokenizers, ONNX, W&B, ZenML, Ragas, DeepEval, ZAP, Wazuh, osquery, CrowdSec, Grype, Syft, Gitleaks, TruffleHog, Semgrep, OSV-Scanner, Keycloak, Ory Kratos and Authelia.

Thirteen working feeds were held back because more than a fifth of their entries were not detected as English. They are mostly release feeds with version-number titles (Apache Pulsar, Fluent Bit, React Router, Vector, VictoriaMetrics, Drizzle, Crystal, ASP.NET Core, .NET Runtime, Teleport, StarRocks, Yarn) and Armin Ronacher's blog. Thirteen were unavailable. The Google blogs (Project Zero, Security, Developers, Android Developers), LangChain and NCC Group could not be fetched from GitHub's network. VideoCardz and BNamericas denied access. Japan Times, Taipei Times, Kevin Lynagh, Ted Unangst and Arabian Business returned no usable feed.

## Round three (2026-11-24)

Validation run #10 checked `source-candidates-2026-11-24-round3.json`, which has 72 candidates. It rechecked 32 feeds that had failed earlier rounds for transient reasons and added 40 new ones. 32 passed and were promoted, and the catalog now has 1,104 enabled sources.

- **Retries that now work (11):** BlaBlaCar, NYT Open, Bolt, QuintoAndar, Thumbtack, Wise, Doctolib, Coursera, FT Product & Technology, iFood and Vimeo.
- **New (21):** Intuit Engineering, Brex Engineering, Zerodha Tech, 9to5Linux, Linuxiac, OMG! Ubuntu, Analytics Vidhya, CIO Dive, CIO.com, Canary Media, CleanTechnica, Finextra, Postman, IBM Research, HubSpot Product, AppleInsider, Daring Fireball, Six Colors, Khan Academy Engineering, Mercado Libre Tech and ShareChat TechByte.

Several feeds failed from GitHub's network again, and GitHub now runs the production sweeps, so they are not added: the Google blogs (Project Zero, Security, Android Developers), Dan Luu, Heroku, Laravel News, LangChain, NCC Group, Elastic Security Labs and rachelbythebay. The Cooperpress newsletters (JavaScript, Golang, Ruby, Postgres Weekly, Frontend Focus) list issues without dates, so they had no eligible entries. Lawfare, Telecoms.com and Fintech Futures denied access.

## Round four from publisher discovery (2026-11-24)

Publisher discovery run #4 scanned 146 new publisher pages (`app/discovery_seeds.json`) and found 87 new feed links. Those were reduced to 40 candidates by dropping comment feeds, duplicate section feeds and site-wide feeds. Validation run #11 checked `source-candidates-2026-11-24-round4.json`, and 35 passed with English confirmed and were promoted. The catalog now has 1,139 enabled sources.

- **AI:** SambaNova, ElevenLabs, Voyage AI, Sierra, Writer and Qodo.
- **Cloud and security:** Istio, Cilium, Isovalent, Chainguard Unchained, Auth0, Horizon3.ai Attack Research and GitGuardian.
- **Regional press:** TheElec (Korea), Rappler Technology (Philippines), Tech In Africa, Euronews Next, ArcticStartup, Maddyness UK, IT Brief New Zealand, IT Brief Australia and Politico Europe Technology.
- **Consumer tech:** PCWorld, PCMag, Forbes Innovation, Vox Technology, Mashable Tech, Digital Trends and Tom's Guide.
- **Engineering writers:** Jack Vanlightly, Gunnar Morling, The Developing Dev, Surfing Complexity, Increment and RISC-V International News.

Five working feeds were held back because their entries could not be confirmed as English: Sakana AI, Honeybadger, BusinessKorea, Two Sigma and the morning paper.

## Round five from publisher discovery (2026-11-24)

Publisher discovery runs #5 to #7 scanned three new seed batches (133, 108 and 81 pages). Their new feed links were reduced to 114 candidates in `source-candidates-2026-11-24-round5.json`. Validation run #12 promoted 106 of them, and the catalog now has 1,245 enabled sources. The reviewed catalog file passed 1,000 entries, so the loader's sanity bound in `load_source_pack` was raised to 3,000.

- **Developer platforms:** Buildkite, Spacelift, Dremio, Tigris, Coder, Depot, Trunk, Zuplo, Ably, Apollo GraphQL, Daily, Mux, Cloudinary, Sanity, Builder.io, Ghost, Nutanix.dev, OVHcloud and Cisco Blogs.
- **Languages, frameworks and open source:** Ruby, Elixir, Spring (plus Spring security advisories), Quarkus, Symfony, foojay, WordPress News and Make WordPress Core, KDE, MariaDB Foundation, the Apache and Eclipse foundations, and Linux kernel releases.
- **AI and research:** Andrej Karpathy, Transformer Circuits, METR, the Centre for the Governance of AI, LAION, Nomic and Intercom.
- **Security and privacy:** Zero Day Initiative, Hackread, Tor Project, Proton, Element, DuckDuckGo Spread Privacy and Access Now.
- **Company newsrooms:** Meta, Reddit, Salesforce, SAP and IBM.
- **Consumer tech, hardware and games:** GSMArena, Android Central, Android Headlines, Droid Life, BGR, SlashGear, Macworld, Cult of Mac, iDownloadBlog, Gizmochina, Liliputing, KitGuru, HotHardware, StorageReview, All About Circuits, Edge AI and Vision, Electronics For You, PC Gamer, Rock Paper Shotgun, Kotaku, Siliconera and Khronos.
- **Science and technology:** New Scientist, Live Science, Popular Science, Popular Mechanics, New Atlas, Singularity Hub and Futurism.
- **Regional, trade and business press:** ProPakistani, Digital News Asia, BusinessWorld, Techzim, France 24, The Recursive, Emerging Europe, City AM, ARN, MobileSyrup, The Logic, The Quint, Petri, Windows Latest, gHacks, Cloud Native Now, Teslarati, The Drive, The Diff, Margins and Newcomer.
- **Engineering writers:** Kent C. Dodds, Total TypeScript, Vlad Mihalcea and Evil Martians.

Render and A List Apart were held back because English could not be confirmed. Green Car Reports, New Statesman, Stainless, thoughtbot, Tyk and Vivaldi were unavailable.

## Round six and the end of this expansion (2026-11-24)

Publisher discovery run #8 scanned 135 regional technology desks and engineering-writer pages. Most of the 80 new links it found were whole general-news feeds (national papers in Nigeria, Ghana, Morocco, Mexico, Argentina, Costa Rica, Ireland, Scotland, Wales, the Netherlands, Lithuania, Ukraine, Portugal, Spain and Italy). These were left out because the catalog lists technology coverage. The remaining 20 went into `source-candidates-2026-11-24-round6.json`, and validation run #13 promoted 17 of them. The catalog now has 1,262 enabled sources.

- **Added:** Deccan Chronicle Technology, Express Computer, Dataquest India, CIOL, DIGITIMES Asia, TahawulTech, TechGuide Australia, Materialized View, Nick Craver, Rakyll, Dave Cheney, Yoshua Wuyts, Writing an OS in Rust, Kalzumeus, Ben Kuhn, Construction Physics and Asterisk.
- **Not reachable from GitHub:** Baby Steps (Niko Matsakis), Korea Tech Desk and Punch Technology.

Yield across the six rounds fell from 130 per round to 17, and most well-known English technology publishers are now covered. Further growth should come from feeds that readers or reviewers notice are missing, not from broad sweeps.
