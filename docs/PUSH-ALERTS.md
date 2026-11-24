# Device alerts (Web Push)

Readers can turn on notifications for the stories, technologies, companies, topics and stack terms they
follow (Tech Radar, technology pages, "Follow company" in For You). The panel is under **For you → Alerts on
this device** and **Research Desk → Tech Radar → Alerts on this device**. The site is also installable as an
app (manifest, icons, service worker with an offline page).

## Turn it on in production

1. On your own computer, in the repository:

   ```
   uv run python -m scripts.generate_vapid_key
   ```

2. In Vercel → Project → Settings → Environment Variables (Production), add:
   - `NEWS_PUSH_VAPID_PRIVATE_KEY` — the value printed above. Keep it secret; changing it later stops every
     existing subscription.
   - `NEWS_PUSH_SUBJECT` (optional) — `mailto:` address or `https://` URL push services can contact.
     Defaults to `PUBLIC_ORIGIN`.
3. Redeploy. `GET /api/push/config` then returns `"enabled": true` and the panel offers **Turn on alerts**.

Without the key the panel says alerts aren't available yet and nothing is stored or sent.

## How alerts are chosen

- After each hourly intelligence check (`/api/jobs/intelligence`), `push_alerts.dispatch` ranks the last
  24 hours of grouped developments with the same follow matching as Tech Radar catch-ups (`followed_only`).
- One notification per reader per run at most, three hours apart, within the reader's daily limit (1, 3 or
  5) and outside quiet hours (22:00–07:00 in the reader's time zone, on by default).
- Only developments updated after alerts were turned on are considered; each development version is sent
  once. Seen history is kept for 14 days.
- The feed schedule is unchanged; alerts only read what the sweeps already stored.

## Privacy and safety

- Stored per browser: push endpoint, its public keys, the follow list and alert settings. No name, email or
  IP address. Payloads are encrypted for the browser (RFC 8291) and signed with VAPID (RFC 8292).
- Endpoints must belong to a known push service (Google, Mozilla, Apple, Microsoft), so the server never
  posts to an address a visitor chose.
- Subscriptions are removed when the push service answers 404/410, after five failed deliveries, when the
  reader turns alerts off or unfollows everything, or when notifications are blocked for the site.
