# Informa AI application security audit

**Date:** 21 November 2026 (IST)
**Scope:** Full source and configuration review of the FastAPI backend, static frontend, Vercel deployment configuration, GitHub workflows, Docker development service, dependencies and Git history. Dynamic testing ran only against a local server with disposable SQLite and PostgreSQL databases. The production site was not probed.
**Baseline:** Follows the [19 November audit](SECURITY-AUDIT-2026-11-19.md). Its fixes were re-checked and still hold.

## Summary

There were no Critical or High findings. The review confirmed two Medium findings, one of them conditional, and five Low findings. All seven are fixed and covered by regression tests. Nine of the 18 new tests target these fixes. All nine fail on the previous code and pass on the fixed code. The other nine guard behaviour that must not change.

| # | Severity | Finding | Status |
| --- | --- | --- | --- |
| 1 | Medium | IPv6 address rotation bypassed every per-IP quota | Fixed |
| 2 | Medium, conditional | Owner token had no strength floor, and owner and scheduler routes had no brute-force throttle | Fixed |
| 3 | Low | `ADMIN_TOKEN` was reused as the HMAC key for preview signatures returned by a public route | Fixed |
| 4 | Low | Production Swagger UI loaded unpinned third-party scripts with `'unsafe-inline'` on the app origin | Fixed |
| 5 | Low | Uncached public database reads had no request budget | Fixed |
| 6 | Low | API responses did not set `Cross-Origin-Opener-Policy` | Fixed |
| 7 | Low | The source-review workflow kept the checkout token on disk | Fixed |

## Findings

### 1. IPv6 rotation bypassed per-IP quotas (Medium)

**Root cause.** `server.client_key()` and `public_mail.address_key()` keyed quotas by the full client address. ISPs and clouds normally give an IPv6 client a /64 or larger, which is 2^64 addresses that the client can choose freely. Each new address got a fresh quota. This affected every IP-scoped control: AI research, explain, catch-up and converse; digest generation; monitor and project creation; mail dispatch; per-IP verification limits; and the discovery check.

**Proof (local).** 32 requests from one IPv6 address to `/api/discovery/check` produced 429 responses. 63 requests from addresses rotated inside one /64 produced none.

**Impact.** One client could drain the shared daily AI budgets (`research.reserve`, `generate-total`), which denies AI features to everyone. It could also inflate database load and exhaust mail capacity. Per-mailbox limits and Turnstile still apply, so a single victim inbox could not be flooded.

**Fix.** The new `app/client_identity.py` maps IPv6 clients to their /64 and IPv4-mapped IPv6 addresses to the IPv4 address. Both quota keys use it. IPv4 keys are unchanged, so existing quota buckets carry over.

### 2. Owner token strength and brute-force throttle (Medium, conditional)

**Root cause.** `require_owner()` accepted an `ADMIN_TOKEN` of any length. No route counted failed bearer attempts against `/api/admin/*`, `/api/email` or `/api/jobs/*`. A short or guessable production token could be found by unlimited online guessing. The impact depends on the production value. The local value is 64 characters.

**Fix.** Tokens shorter than 32 characters are treated as unset. Owner routes then return 401 and a warning is logged. The middleware counts 401 responses on privileged paths per client. After 10 failures within 15 minutes it returns 429 with `Retry-After` before the handler runs. Public routes are not affected.

### 3. Owner token reused as a public MAC key (Low)

**Root cause.** `signature()` computed HMAC-SHA256 with the raw `ADMIN_TOKEN`. The resulting MAC was returned by `POST /api/digest` to anyone. HMAC does not reveal its key, but one secret served two purposes, and any later bug in either purpose would affect the other.

**Fix.** Previews are now signed with a key derived as `HMAC(ADMIN_TOKEN, "informa:preview-signature:v1")`.

### 4. Swagger UI on the production origin (Low)

**Root cause.** `/api/docs` served FastAPI's Swagger page. That page loads `swagger-ui-dist@5` from jsDelivr with no Subresource Integrity, and its route-specific CSP allows `'unsafe-inline'`. If the CDN package were compromised, the script would run on getinformdaily.com. From there it could send same-origin requests that carry the HttpOnly mail and monitoring cookies.

**Fix.** Swagger UI is off in Vercel production unless `API_DOCS_ENABLED=1` is set. It stays on in local and preview environments. `/openapi.json` is unchanged.

### 5. Unbudgeted public database reads (Low)

**Root cause.** Several GET routes go to the database and are not served from the CDN cache. They had no request budget. `/api/authors`, for example, scans the full recent sample on every call. Others were search on `/api/news`, article details, developments, coverage, source health, technologies, briefing and search suggestions.

**Fix.** The middleware applies per-client budgets from the `READ_LIMITS` table, per minute: 30 for authors and coverage, 60 to 120 for most reads, and 240 for type-ahead suggestions. Over-budget requests get 429 with `Retry-After`. These budgets apply per instance and work alongside the edge cache. They do not replace platform rate limiting.

### 6. Missing opener isolation (Low)

**Fix.** `Cross-Origin-Opener-Policy: same-origin` is now set on application responses and in the global headers in `vercel.json`.

### 7. Persisted checkout token in source-review.yml (Low)

**Root cause.** The manual workflow runs publisher-discovery scripts after a checkout that kept the `GITHUB_TOKEN` in `.git/config`.

**Fix.** `persist-credentials: false` is set, matching `ci.yml`.

## Controls re-verified with no finding

- **Injection.** All SQL goes through SQLAlchemy Core with bound parameters. `contains(..., autoescape=True)` is used throughout. DDL f-strings use only schema-defined names.
- **XSS.** The frontend never assigns API data to `innerHTML`. It builds DOM nodes, allows only `https:` links and runs reading content through an element allowlist. Email HTML is escaped in `safe_email_html`. Contributed Markdown is sanitised server-side and again client-side. The CSP has no inline scripts or styles.
- **CSRF.** Origin and `Sec-Fetch-Site` checks cover every write method. Session cookies are `SameSite=Strict`, path-scoped and HttpOnly. Cross-site POSTs were confirmed to return 403.
- **SSRF.** No user-supplied URL is fetched. Workspace webhooks are restricted to Slack and Teams hosts, with redirects disabled. Feed ingestion fetches only reviewed sources. Sitemap XML refuses DTDs, and the expat version is 2.6.1.
- **Authorization and IDOR.** Mail sessions are HMAC-sealed and revocable. Contributions are scoped to the mailbox. Monitors, projects and alerts are scoped to the profile. Shared brief and invite tokens are 256-bit, single-use where intended, and expire.
- **Verification codes.** Each code allows 5 tries, and each mailbox gets 3 codes a day. Turnstile checks action and hostname.
- **Webhooks and crons.** Resend events use Svix HMAC with a 5-minute skew limit. Job routes use bearer secrets compared in constant time.
- **Secrets.** No live credential was found in tracked files or in the full Git history. `.env` is ignored by Git and excluded from Vercel deployments.
- **Dependencies.** `pip-audit` found 0 known vulnerabilities in the locked runtime packages. `npm audit` found 0.

## Verification

| Check | Result |
| --- | --- |
| Backend tests with SQLite and PostgreSQL 16 | 412 passed, 0 skipped. This includes 18 new security regressions. |
| Frontend tests, lint and production build | 70 of 70 passed. Build validated. |
| Ruff and compileall | Clean |
| Mail capacity rehearsal on PostgreSQL | 10,000 recipients, zero duplicates |
| Reader quality replay | Passed |
| Local uvicorn smoke test | Home page, news, search, briefing, headlines, Curiosity, developments, suggestions, OpenAPI and setup all returned 200. A cross-site POST returned 403. The 11th bad owner token returned 429. |
| Headless Chromium, 5 pages | Loaded with no console errors |

## Remaining risks and manual configuration

1. **Before deploying,** confirm the production `ADMIN_TOKEN` is at least 32 characters. If it is not, rotate it with `openssl rand -hex 32` using `scripts/sync_vercel_env.py`. Otherwise owner tools will return 401.
2. Preview signatures change with this release. Any `/api/email` preview created less than an hour before the deploy must be regenerated.
3. App-level limits apply per serverless instance. For limits that hold across all instances, add Vercel Firewall rate-limit rules for `/api/*`, especially the AI routes. The global daily AI budgets remain the hard ceiling.
4. Consider adding `includeSubDomains; preload` to HSTS once every getinformdaily.com subdomain is HTTPS-only. This was left unchanged because it cannot be verified from source.
5. Use distinct, 32-character or longer values for `CRON_SECRET` and `FEED_REFRESH_SECRET`. The code still accepts 16 characters for compatibility.
6. Accepted by design: project collaborators can create and revoke shared brief links. `/api/mail/challenge` reveals that an address is suppressed, but only after Turnstile. Answers built from feed content can still be influenced by prompt injection, though they are labelled and rendered as text.
7. The operational checks listed in the 19 November audit still apply: database role privileges, TLS to the database and Redis, and log redaction.
