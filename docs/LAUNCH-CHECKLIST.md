# Launch checklist and promotion kit

What to switch on after deploying, how to watch the site, and ready-to-edit launch posts.
Numbers below come from the repository on 24 November 2026; recheck them before posting.

## 1. Switch on what is built (owner, once)

- [ ] **Device alerts:** run `uv run python -m scripts.generate_vapid_key` on your computer and add the value to
      Vercel → Settings → Environment Variables (Production) as `NEWS_PUSH_VAPID_PRIVATE_KEY`. Redeploy, open
      For you → Alerts on this device, follow a technology, turn alerts on and press **Send a test alert**.
- [ ] **Weekly recap:** in GitHub → Actions, run **Prepare weekly recap** once (it then runs daily at 06:17 IST),
      and open `/recap.html`.
- [ ] **Site health:** run **Site health** once from Actions; it then runs daily at 05:11 IST and fails when a
      page, API or feed is down. Turn on GitHub email notifications for failed workflows.
- [ ] **Feedback:** send yourself a test from the footer link, then read it:
      `curl -H "Authorization: Bearer $ADMIN_TOKEN" https://getinformdaily.com/api/admin/feedback`.
- [ ] **Install:** on Android Chrome or desktop Chrome/Edge, check the sidebar shows **Install the app**; on
      iPhone, Share → Add to Home Screen, then turn on alerts from the installed app.

## 2. Get found (owner)

- [ ] **Google Search Console:** add `getinformdaily.com` (DNS verification), then submit
      `https://getinformdaily.com/sitemap.xml` and `https://getinformdaily.com/sitemap-cards.xml`.
- [ ] **Bing Webmaster Tools:** import the site from Search Console (one click).
- [ ] **Feed directories:** add `/feeds/latest.xml`, `/feeds/recap.xml` and `/feeds/curiosity.xml` to your own
      Feedly and Inoreader accounts; public feeds are indexed after the first subscriber.
- [ ] **Social previews:** paste a card page (`/cards/...`), `/recap.html` and `/trackers.html` into the LinkedIn
      Post Inspector and check the preview.

## 3. Watch what readers do (monthly)

The monthly Curiosity upkeep report (GitHub Actions artifact) now includes reader feedback counts and the
"Was this page useful?" yes/no split per page. Messages themselves stay behind `/api/admin/feedback`.

Decide after 3–4 weeks of real use:

| Signal | Where | Means |
| --- | --- | --- |
| Pages people return to | Vercel Analytics (opted-in readers) | Which surfaces to grow |
| Alerts turned on, RSS subscribers | `brief_push_subscriptions` count, feed reader stats | Whether follow-and-notify is worth more work |
| Morning brief opens | Resend dashboard | Whether email stays the core habit |
| "Was this useful?" no-votes and messages | Monthly report, `/api/admin/feedback` | What to fix first |

## 4. Launch posts (edit before posting)

Keep claims to what the site does today. Post in one place at a time and reply to every comment.

### Show HN

> **Show HN: Informa AI – global tech news from 1,300+ sources, with trackers and engineering case studies**
>
> I built Informa AI (getinformdaily.com) because I was checking a dozen sites every morning. It reads reviewed
> RSS feeds from about 1,370 technology publishers, official blogs, status pages, advisories and release feeds,
> and shows headlines with short excerpts and a link to the original. It never republishes full articles.
>
> Things that might be useful to HN readers:
> - Trackers for AI model launches, provider incidents, exploited CVEs and the latest release of each tracked
>   open-source project (/trackers.html).
> - Curiosity Cards: 180+ reviewed engineering postmortems and case studies, with what broke and how teams fixed it.
> - RSS out for any topic, technology or search, and a weekly recap.
> - "First reported by" and region breakdowns when several outlets cover the same story.
>
> Stack: FastAPI, Postgres, vanilla JS on Vercel; feeds are fetched by GitHub Actions twice a day. Feedback
> is very welcome (there's a link in every footer).

### LinkedIn

> I've been building Informa AI — one place to follow global tech and AI news without visiting 20 sites.
>
> This week it gained live trackers (AI model launches, outages, exploited vulnerabilities, major releases),
> a weekly "This week in tech" recap, RSS feeds for any topic, and alerts for the stories and technologies you follow.
>
> Every story links to the original publisher. If you try it, I'd love to hear what's missing:
> https://getinformdaily.com

### X / short post

> Built a tech-news hub that tracks AI model launches, outages, exploited CVEs and releases in one place, plus
> 180+ real engineering postmortems. Links to the original sources, RSS for anything. Feedback welcome →
> https://getinformdaily.com/trackers.html

### Communities

- r/programming, r/devops, r/sysadmin: lead with the incident board or a Curiosity reading list, not the homepage.
- r/developersIndia and Indian developer groups: lead with "Engineering at India scale" (`/curiosity.html?list=engineering-at-india-scale`).
- Read each community's self-promotion rules first; many allow it only in a weekly thread.
