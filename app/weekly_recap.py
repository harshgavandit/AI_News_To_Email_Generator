"""This week in tech: a weekly recap page, RSS item and Monday email section.

A recap covers one ISO week (Monday 00:00 to Monday 00:00 UTC). It is built once from what the sweeps
stored, without model calls, and saved as a snapshot so past weeks stay readable after their articles
age out of the archive.
"""
from datetime import UTC, datetime, timedelta
from html import escape
import json
import logging
import re
import time

from fastapi import APIRouter, HTTPException, Path, Response
from sqlalchemy import Column, Float, String, Table, Text, inspect, select

from app.cache import Cache
from app.coverage import TOPICS, public_article
from app.feeds import latin_headline
from app.launch_store import articles, get_store, schema

logger = logging.getLogger(__name__)
router = APIRouter()
_partial_cache = Cache("weekly-recap-partial-v2")

weekly_recaps = Table("brief_weekly_recaps", schema,
    Column("week", String(10), primary_key=True), Column("payload", Text, nullable=False),
    Column("created", Float, nullable=False))
WEEK_ID = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")
BUILDABLE_WEEKS = 10  # the archive keeps about 90 days of articles
TOP_STORIES = 10
PER_TOPIC = 3


def week_id(moment):
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(ident):
    start = datetime.strptime(ident + "-1", "%G-W%V-%u").replace(tzinfo=UTC)
    return start, start + timedelta(days=7)


def last_complete_week(now=None):
    now = now or datetime.now(UTC)
    return week_id(now - timedelta(days=7))


def ensure(store):
    if getattr(store, "_recap_ready", False):
        return
    with store.engine.begin() as conn:
        if not inspect(conn).has_table(weekly_recaps.name):
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
            weekly_recaps.create(conn, checkfirst=True)
    store._recap_ready = True


def week_stories(store, start, end):
    """Developments that gained coverage this week, ranked by how many publishers covered them that week."""
    from app import event_intelligence
    if not event_intelligence.ready(store):
        return []
    events, items = event_intelligence.events, event_intelligence.event_items
    with store.engine.connect() as conn:
        statement = (store.query(int((datetime.now(UTC) - start).total_seconds() // 3600) + 1)
                     .join(items, items.c.article_id == articles.c.id).add_columns(items.c.event_id, events.c.topic)
                     .join(events, events.c.id == items.c.event_id)
                     .where(articles.c.published_at >= start.isoformat(), articles.c.published_at < end.isoformat()))
        rows = conn.execute(statement).mappings().all()
    groups = {}
    for row in rows:
        groups.setdefault(row["event_id"], []).append(dict(row))
    stories = []
    for ident, material in groups.items():
        cleaned = [public_article(row) for row in material]
        english = [row for row in cleaned if latin_headline(row["title"])]
        if not english:
            continue
        english.sort(key=lambda row: (row["publishedAt"], row["id"]))
        publishers = {row.get("publisher_family") or row["sourceName"] for row in english}
        lead = english[-1]
        stories.append({"id": ident, "title": lead["title"], "topic": material[0]["topic"],
                        "topic_label": TOPICS.get(material[0]["topic"], "Technology"),
                        "outlets": len(publishers), "articles": len(english), "first_reported": english[0]["publishedAt"],
                        "first_publisher": english[0]["sourceName"],
                        "summary": (lead.get("cleanSummary") or "")[:280],
                        "url": f"/development.html?id={ident}",
                        "sources": [{"title": row["title"], "url": row.get("original_url") or row["sourceUrl"],
                                     "publisher": row["sourceName"]} for row in english[::-1][:3]]})
    stories.sort(key=lambda story: (story["outlets"], story["articles"], story["first_reported"]), reverse=True)
    return stories


def headline_stories(store, start, end, exclude=(), limit=TOP_STORIES):
    """Fallback when few developments were grouped that week: the reporting headlines with the strongest signals."""
    from app.news_signals import impact_score, story_signals
    statement = (store.query(7 * 24, coverage="reporting", now=end).where(articles.c.published_at >= start.isoformat())
                 .order_by(articles.c.published_at.desc()).limit(3000))
    with store.engine.connect() as conn:
        rows = [public_article(dict(row)) for row in conn.execute(statement).mappings()]
    seen_titles, picks, per_signal, per_publisher = set(exclude), [], {}, {}
    for row in sorted(rows, key=lambda row: (impact_score(row), row["publishedAt"]), reverse=True):
        key = " ".join(row["title"].casefold().split()[:6])
        signal = (story_signals(row) or [{"id": "other"}])[0]["id"]
        publisher = row.get("publisher_family") or row["sourceName"]
        # Spread picks across kinds of news and publishers rather than ten outage headlines.
        if (key in seen_titles or not latin_headline(row["title"]) or impact_score(row) <= 0
                or per_signal.get(signal, 0) >= 2 or per_publisher.get(publisher, 0) >= 2):
            continue
        seen_titles.add(key)
        per_signal[signal] = per_signal.get(signal, 0) + 1
        per_publisher[publisher] = per_publisher.get(publisher, 0) + 1
        link = row.get("original_url") or row["sourceUrl"]
        picks.append({"id": row["id"], "title": row["title"], "topic": row["category"], "topic_label": TOPICS.get(row["category"], "Technology"),
                      "outlets": 1, "articles": 1, "first_reported": row["publishedAt"], "first_publisher": row["sourceName"],
                      "summary": (row.get("cleanSummary") or "")[:280], "url": link,
                      "sources": [{"title": row["title"], "url": link, "publisher": row["sourceName"]}]})
        if len(picks) >= limit:
            break
    return picks


def build(store, ident):
    from app import trackers
    start, end = week_bounds(ident)
    stories = week_stories(store, start, end)
    grouped = [story for story in stories if story["outlets"] >= 2]
    if len(grouped) < TOP_STORIES:
        known = {" ".join(story["title"].casefold().split()[:6]) for story in grouped}
        stories = grouped + headline_stories(store, start, end, known, TOP_STORIES - len(grouped)) + \
            [story for story in stories if story["outlets"] < 2]
    top = stories[:TOP_STORIES]
    shown = {story["id"] for story in top}
    topics = []
    for key, label in TOPICS.items():
        picks = [story for story in stories if story["topic"] == key and story["id"] not in shown][:PER_TOPIC]
        if picks:
            topics.append({"id": key, "label": label, "stories": picks})
    models = trackers.ai_models(store, 7, now=end)
    incidents = trackers.incidents(store, 7, now=end)
    security = trackers.security(store, 7, now=end)
    releases = [item for item in trackers.releases(store, 7, now=end) if item["level"] in {"major", "minor"}]
    try:
        from app.curiosity import postmortem_of_the_week
        postmortem = postmortem_of_the_week(start)
    except Exception as error:  # noqa: BLE001 - the recap is still useful without it
        logger.warning("recap_postmortem_unavailable error_type=%s", type(error).__name__)
        postmortem = None
    return {
        "week": ident, "start": start.date().isoformat(), "end": (end - timedelta(days=1)).date().isoformat(),
        "title": f"This week in tech: {start:%b} {start.day} – {(end - timedelta(days=1)):%b} {(end - timedelta(days=1)).day}, "
                 f"{(end - timedelta(days=1)).year}",
        "complete": len(grouped) >= 5,
        "stats": {"developments": len(stories), "models": len(models), "providers_with_incidents": len(incidents["providers"]),
                  "cves": len(security["cves"]), "exploited": sum(item["exploited"] for item in security["cves"]),
                  "releases": len(releases)},
        "top_stories": top, "topics": topics,
        "models": [{"name": item["name"], "official": item["official"], "outlets": item["outlets"],
                    "url": item["headline"]["url"], "publisher": item["headline"]["publisher"]} for item in models[:8]],
        "incidents": [{"provider": item["provider"], "updates": len(item["updates"]), "latest": item["updates"][0]["title"],
                       "url": item["updates"][0]["url"]} for item in incidents["providers"][:8]],
        "exploited": [{"cve": item["cve"], "title": item["headline"]["title"], "url": item["headline"]["url"]}
                      for item in security["cves"] if item["exploited"]][:8],
        "releases": [{"project": item["project"], "version": item["version"], "level": item["level"],
                      "url": item["release"]["url"]} for item in releases[:12]],
        "postmortem": ({"id": postmortem["id"], "title": postmortem["title"], "url": postmortem["url"],
                        "company": postmortem.get("company") or postmortem.get("publisher") or ""} if postmortem else None),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "notice": "Built from publisher coverage stored that week. Rankings count publishers, not importance.",
    }


def load(store, ident):
    ensure(store)
    with store.engine.connect() as conn:
        row = conn.execute(select(weekly_recaps.c.payload).where(weekly_recaps.c.week == ident)).first()
    payload = json.loads(row.payload) if row else None
    return payload if payload and payload.get("top_stories") else None  # an empty snapshot is rebuilt


def save(store, ident, payload):
    ensure(store)
    with store.engine.begin() as conn:
        found = conn.execute(select(weekly_recaps.c.payload).where(weekly_recaps.c.week == ident)).first()
        if found is None:
            conn.execute(weekly_recaps.insert().values(week=ident, payload=json.dumps(payload), created=time.time()))
        elif not json.loads(found.payload).get("top_stories"):
            conn.execute(weekly_recaps.update().where(weekly_recaps.c.week == ident)
                         .values(payload=json.dumps(payload), created=time.time()))


def recap(store, ident, *, now=None):
    """A finished week's recap, built and saved on first use. Returns None for weeks that cannot be built."""
    saved = load(store, ident)
    if saved:
        return saved
    start, end = week_bounds(ident)
    now = now or datetime.now(UTC)
    if end > now or now - end > timedelta(weeks=BUILDABLE_WEEKS):
        return None
    cached, _ = _partial_cache.get(ident)
    if cached:
        return cached
    payload = build(store, ident)
    if payload["complete"]:
        save(store, ident, payload)
    else:
        # Too little grouped coverage to freeze (for example right after the archive started): serve it,
        # and try again later.
        _partial_cache.put(ident, payload, ttl=1800, stale=0)
    return payload


def available(store, limit=26):
    ensure(store)
    with store.engine.connect() as conn:
        rows = conn.execute(select(weekly_recaps.c.week, weekly_recaps.c.payload)
                            .order_by(weekly_recaps.c.week.desc()).limit(limit)).all()
    return [{"week": row.week, "title": payload["title"]} for row in rows
            if (payload := json.loads(row.payload)).get("top_stories")]


def latest(store, now=None):
    return recap(store, last_complete_week(now), now=now)


def archive():
    store = get_store()
    if not store:
        raise HTTPException(503, "The weekly recap is unavailable right now.")
    return store


def respond(response, payload, store):
    if payload is None:
        raise HTTPException(404, "No recap for that week.")
    response.headers["Cache-Control"] = "public, max-age=600"
    response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=1800, stale-while-revalidate=86400"
    return {**payload, "weeks": available(store)}


@router.get("/api/recap")
def latest_recap(response: Response):
    store = archive()
    return respond(response, latest(store), store)


@router.get("/api/recap/{ident}")
def week_recap(response: Response, ident: str = Path(pattern=WEEK_ID.pattern)):
    store = archive()
    return respond(response, recap(store, ident), store)


# --- Monday email section -------------------------------------------------------------------------

def email_block(payload, site):
    """Five biggest stories of last week, for the Monday morning brief."""
    stories = (payload or {}).get("top_stories", [])[:5]
    if not stories:
        return "", ""
    link = f"{site}/recap.html?week={payload['week']}"
    items_html = "".join(
        f'<li style="margin:0 0 10px;"><a href="{escape(site + story["url"], quote=True)}" style="color:#0b3a78;font-weight:600;">'
        f'{escape(story["title"][:200])}</a><br><span style="font-size:12px;color:#5b6b80;">{escape(story["topic_label"])} · '
        f'{story["outlets"]} publishers</span></li>' for story in stories)
    stats = payload["stats"]
    line = (f'{stats["models"]} AI models, {stats["exploited"]} exploited vulnerabilities and '
            f'{stats["releases"]} major or minor releases tracked.')
    html = ('<div style="margin:16px 0 0;padding:16px;border-radius:8px;background:#f3f7fc;">'
            '<h2 style="font:600 20px/1.3 Georgia,serif;color:#0b1f3a;margin:0 0 6px;">Last week in tech</h2>'
            f'<p style="font-size:12px;color:#5b6b80;margin:0 0 12px;">{escape(line)}</p>'
            f'<ol style="padding-left:18px;margin:0 0 8px;">{items_html}</ol>'
            f'<a href="{escape(link, quote=True)}" style="font-size:12px;color:#0b3a78;">See the full weekly recap →</a></div>')
    markdown = ("## Last week in tech\n\n" + line + "\n\n"
                + "\n".join(f"{index}. {story['title']} ({story['outlets']} publishers) — {site}{story['url']}"
                            for index, story in enumerate(stories, 1))
                + f"\n\nFull recap: {link}")
    return html, markdown


def append_to_brief(brief, payload, site):
    html, markdown = email_block(payload, site)
    if not html:
        return brief
    return dict(brief, markdown=f'{brief["markdown"]}\n\n{markdown}',
                html=brief["html"].replace("</body>", f"{html}</body>") if "</body>" in brief["html"] else brief["html"] + html)
