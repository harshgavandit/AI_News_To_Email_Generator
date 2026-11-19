# Informa AI application security audit

**Date:** 19 November 2026 (IST)
**Assessment:** Source and configuration review, local regression tests, dependency advisory checks, and passive production header verification.

The review confirmed one conditional High finding, four Medium findings, and three Low findings. No Critical finding was confirmed.

## Findings and fixes

| Severity | Finding and impact | Fix |
| --- | --- | --- |
| High, conditional | The legacy Anthropic pipeline fetched article links supplied by an upstream feed with automatic redirects. If that worker were enabled and the feed or a redirect were compromised, the worker could reach destinations outside the publisher. The current public API uses a separate ingestion path. | The legacy pipeline now uses the same bounded HTTPS transport as the reviewed feed reader. Article fetches require a reviewed Anthropic host, and redirects must stay on that host. RSS is downloaded as bounded bytes before parsing. |
| Medium | The owner Gmail sender used the library's implicit TLS context. In an environment where outbound traffic could be intercepted, the sender lacked explicit hostname and certificate verification before SMTP authentication. | The SMTP client uses a certificate-verifying TLS context. A regression test inspects the context and exercises the send flow with a mock transport. |
| Medium | Mail sign-out removed browser cookies while signed sessions still remained valid until expiry. This affected a session token that had already been copied. | Sign-out durably revokes only the current token using a keyed digest and cancels any outstanding verification code in the same browser. All mail-session consumers check revocation. New sessions have independent nonces, and older sessions can still sign out. |
| Medium | The general write-origin check covered POST and PATCH. PUT and DELETE were left to route-specific protections or browser preflight, and the origin comparison omitted the scheme. DELETE also missed the general request-body cap. | The shared middleware checks POST, PUT, PATCH, and DELETE, matches the complete origin, rejects cross-origin browser fetch metadata, and applies the existing size cap and length validation to each write method. Signed provider and bearer-authenticated service requests can continue without a browser Origin. No cross-site account access was demonstrated. |
| Medium, local configuration | The development database published a default PostgreSQL port on all interfaces with development credentials. Reachability depended on the host firewall and Docker networking. | The published port binds to loopback. Existing environment overrides for credentials and port remain available. |
| Low | Production served Research Projects and Technology without a Content Security Policy. The static index alias also lacked a matching policy in deployment configuration. | Added edge policies for all three paths, denied object embedding in application responses, and set restrictive permissions for camera, microphone, and geolocation. |
| Low | Workspace delivery accepted verified mail sessions but lived outside their cookie path. It also lacked a quota tied directly to the verified mailbox. | The browser posts to `/api/mail/workspace` using the scoped cookie. Mailbox, destination, and IP quotas share the existing atomic reservation. The legacy API path remains available to authenticated clients. |
| Low | The local credential file exclusions in Git and deployment differed. The legacy worker could print raw exception text and tracebacks. | Deployment exclusions now cover credential artifacts and local deployment metadata. Legacy worker failures record the exception type and a generic result. The CI checkout token is read-only and is not persisted. |

## Controls reviewed

- Owner and scheduler bearer authorization, mailbox verification and delivery, browser-bound monitoring, project membership and sharing, submission ownership, and editorial approval. Jobs and webhook event handlers retain their existing authenticated or signed entry points.
- SQLAlchemy parameter binding, search and vector queries, archive and permission storage, publisher link validation, HTML and Markdown rendering, email payload construction, and static and dynamic response headers. The reviewed request-to-query and request-to-render paths did not establish SQL injection, stored XSS, or cross-account object access.
- Public request costs, digest caches, synthesis budgets, delivery reservations, opt-in subscriptions, and scheduled worker leases. Quotas continue to depend on the platform supplying the intended client IP and on a usable shared database.
- Deployment packaging, workflow permissions, the Docker development service, and locked runtime dependencies. The redacted tracked-file and targeted history checks found sample database credentials and public URL slugs that matched secret-like patterns. They did not establish a leaked live credential.

## Verification

- Passive production HEAD requests returned HTTP 200 for the home, Projects, and Technology pages. Only the home page returned Content Security Policy at the time of the check. HSTS, frame protection, MIME sniffing protection, and referrer policy were present on all three responses.
- PyPI advisory scanning reported zero known vulnerabilities across 45 locked runtime packages selected for the audit environment. The npm audit reported zero vulnerabilities in the JavaScript lockfile. CI now repeats advisory checks.
- Local regression tests use disposable SQLite stores, in-process API requests, and provider mocks. The test runner blocks external connections. PostgreSQL coverage requires a disposable service, and the local Docker daemon was unavailable.
- The full backend run passed 323 tests and skipped 34 PostgreSQL tests. All 57 frontend tests, the production asset build, Python lint and compilation, and whitespace checks passed.

## Production release

The security changes were applied to the current production source base and released in commit `911d650a3342449c2864ac54cf92658eab844715`. The owner-authenticated setup endpoint reported a ready PostgreSQL schema and a trigram search index before promotion. The isolated release suite passed all 358 backend tests with PostgreSQL and the frontend checks passed. Production checks confirmed the browser headers on Projects and Technology, the expected `app.js` bytes, the workspace API route, and an archived news query. Readiness returned HTTP 200 with 510 fresh feeds and three failed checks. The release did not trigger publisher refreshes.

## Remaining operational checks

1. Confirm the production PostgreSQL runtime role has only the privileges required for normal operation. Confirm the production PostgreSQL and Redis TLS settings.
2. Confirm the owner, scheduler, mail session, and provider secrets are independently generated and access-controlled. Review hosting and gateway log redaction for query strings, cookies, unsubscribe links, authorization headers, and webhook credentials.
3. Use isolated staging accounts for provider-level delivery, subscription, sign-out, and scheduler verification. Production smoke checks used read-only public requests and the additive owner setup call.
4. Verify production rate-limit identity at the trusted proxy, monitor quota and authorization failures, and keep deployment metadata and backups private. The current scheduler credentials can authorize multiple job families, so treat both as privileged service credentials.
