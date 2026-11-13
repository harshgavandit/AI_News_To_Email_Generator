# AI Brief release operations

The website stays on Vercel. The hosted archive needs the dedicated Neon PostgreSQL database. Before sending any mail, enable the pilot on a release and verify the sender, the allowed hostname and the recipient boundary.

- `NEWS_DATABASE_URL`: pooled PostgreSQL connection with TLS. Run the owner-authenticated `POST /api/admin/setup` once, then `POST /api/admin/refresh` to backfill recent stories. The job at `GET /api/jobs/refresh` uses `CRON_SECRET` and updates feeds, never sends mail.
- `PUBLIC_ORIGIN`: deployed app origin. Turnstile site and secret keys must match the origin hostname. The verified action is `verify_email`.
- `MY_EMAIL`, `APP_PASSWORD`: configured Gmail sender for the initial limited release. Keep secrets in Vercel. Use a separate transactional sender on a verified domain before substantially increasing volume.
- `MAIL_SESSION_SECRET`: random secret of at least 32 characters. Rotation expires verified sessions.
- `PUBLIC_EMAIL_ENABLED=1` enables the mail flow only when the required services are configured. Use `MAIL_PILOT_MODE=1` during the pilot; only the configured Gmail address can receive mail. To pause sending, set `PUBLIC_EMAIL_ENABLED=0` and redeploy.

The app permits three digest reservations per verified mailbox per UTC day. Separate code and app-wide quotas also apply. Gmail aliases are normalized for quota purposes. An uncertain SMTP result keeps the reservation: retrying the same message could send a duplicate. Accepted means Gmail took the message for delivery; inbox placement is a separate check.

Readers get one on-demand digest per send request. The site does not create subscribers or send recurring messages. The owner source page enables or pauses reviewed feeds. Source additions remain reviewed in code so the web app never fetches arbitrary URLs. Expired verification records and previews are pruned during refresh.
