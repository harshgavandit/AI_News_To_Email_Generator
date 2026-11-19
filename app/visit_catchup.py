"""Build an anonymous catch-up from the retained archive and event observations."""

from collections import Counter
from datetime import UTC, datetime, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, or_

from app import event_intelligence, research
from app.coverage import public_article
from app.intelligence import story_identity
from app.launch_store import articles
from app.news_signals import MATERIAL_TERMS, impact_score, news_score
from app.sources import BY_ID
from app.story_coverage import coverage_match, headline

MAX_WINDOW = timedelta(days=7)
DEFAULT_WINDOW = timedelta(hours=24)
EVIDENCE_LIMIT = 8
CANDIDATE_LIMIT = 160
ELIGIBLE_SOURCES = tuple(source.id for source in BY_ID.values() if source.coverage in {
    "advisory", "journal", "preprint", "publisher", "release", "reporting", "status",
})
NOTICE = ("This selection uses publisher publication times and, where available, event index observations. "
          "Observations show when Informa grouped a report or detected a change. Sources can be incomplete.")


class VisitCatchupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    since: AwareDatetime | None = None
    as_of: AwareDatetime | None = None
    analyze: bool = Field(default=False, strict=True)

    @field_validator("since", "as_of", mode="before")
    @classmethod
    def utc_timestamp(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 35 or "T" not in value:
            raise ValueError("Use an ISO 8601 timestamp in UTC.")
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("Use an ISO 8601 timestamp in UTC.") from None
        if instant.utcoffset() != timedelta(0):
            raise ValueError("Use an ISO 8601 timestamp in UTC.")
        return instant.astimezone(UTC)


def visit_window(body, now=None):
    now = now or datetime.now(UTC)
    as_of = body.as_of or now
    if not now - MAX_WINDOW <= as_of <= now or (body.since and body.since > as_of):
        raise ValueError("Choose a previous visit time and a catch-up end within the last seven days.")
    earliest = as_of - MAX_WINDOW
    requested = body.since or as_of - DEFAULT_WINDOW
    if requested < earliest:
        return earliest, as_of, "clamped"
    return requested, as_of, "since_visit" if body.since else "first_visit"


def archive_rows(store, since, as_of):
    """Use immutable event observations, never the last time an unchanged row was checked."""
    lower, upper = since.isoformat(), as_of.isoformat()
    base = store.query(90 * 24, now=as_of).where(articles.c.source_id.in_(ELIGIBLE_SOURCES))
    material_title = or_(*(articles.c.search_title.contains(term, autoescape=True) for term in MATERIAL_TERMS))
    published = base.where(articles.c.published_at > lower)
    event_ready = event_intelligence.ready(store)
    if event_ready:
        items = event_intelligence.event_items
        published = published.outerjoin(items, items.c.article_id == articles.c.id).add_columns(items.c.event_id)
    published = published.order_by(case((material_title, 1), else_=0).desc(),
        articles.c.published_at.desc(), articles.c.id).limit(CANDIDATE_LIMIT)
    observed = None
    if event_ready:
        updates, events = event_intelligence.event_updates, event_intelligence.events
        observed = base.join(updates, updates.c.article_id == articles.c.id).join(events, events.c.id == updates.c.event_id)
        seen_at = updates.c.observed.label("observed")
        significant = updates.c.reason == "source_revision"
        if event_intelligence.revisions_ready(store):
            revisions = event_intelligence.event_revisions
            observed = observed.outerjoin(revisions, updates.c.id == revisions.c.update_id)
            significant = or_(significant, revisions.c.revision > 1)
        observed = observed.add_columns(updates.c.event_id, seen_at, updates.c.reason.label("update_reason"),
            updates.c.title.label("observed_title"), updates.c.excerpt.label("observed_excerpt"),
            updates.c.published_at.label("observed_published_at"), significant.label("event_change")).where(
            events.c.updated > since.timestamp(), updates.c.observed > since.timestamp(),
            updates.c.observed <= as_of.timestamp(), updates.c.published_at <= upper).order_by(
            case((significant, 1), else_=0).desc(), case((material_title, 1), else_=0).desc(),
            seen_at.desc(), updates.c.id).limit(CANDIDATE_LIMIT)
    with store.engine.connect() as conn:
        publications = [dict(row) for row in conn.execute(published).mappings()]
        observations = [dict(row) for row in conn.execute(observed).mappings()] if observed is not None else []
    return publications, observations


def select_rows(publications, observations, since, as_of):
    candidates = {}
    lower = since.isoformat()
    for row in publications:
        candidates[row["id"]] = {**row, "change_type": "published", "observed_at": None, "update_reason": None}
    for row in observations:
        publication = row["observed_published_at"]
        observed_at = datetime.fromtimestamp(row["observed"], UTC).isoformat()
        kind = "event_update" if row["event_change"] else "published" if publication > lower else "newly_observed"
        existing = candidates.get(row["id"])
        if existing and existing["observed_at"] and (
                existing["change_type"] == "event_update" and kind != "event_update"
                or existing["observed_at"] >= observed_at):
            continue
        candidates[row["id"]] = {**row, "title": row["observed_title"], "description": row["observed_excerpt"],
            "published_at": publication, "change_type": kind, "observed_at": observed_at}

    def ordering(row):
        is_update = row["change_type"] == "event_update"
        effective_date = row["published_at"] if row["change_type"] == "published" else row["observed_at"]
        return (news_score({**row, "published_at": effective_date}, as_of) + (8 if is_update else 0),
                effective_date, row["id"])

    result, identities, event_ids, headlines = [], set(), set(), []
    publishers = Counter()
    for row in sorted(candidates.values(), key=ordering, reverse=True):
        if impact_score(row) < 0:
            continue
        article = public_article(row)
        identity = story_identity(article)
        family, event_id = article["publisher_family"], row.get("event_id")
        if identity in identities or event_id in event_ids or publishers[family] >= 2:
            continue
        current = headline(article)
        if any((not event_id or not previous_event) and coverage_match(current, prior)
               for previous_event, prior in headlines):
            continue
        identities.add(identity)
        headlines.append((event_id, current))
        if event_id:
            event_ids.add(event_id)
        publishers[family] += 1
        result.append({**research.evidence_record(article), "event_id": event_id,
            "change_type": row["change_type"], "observed_at": row["observed_at"],
            "update_reason": row["update_reason"] if row["change_type"] == "event_update" else None,
            "date_precision": article.get("publication_date_precision")})
        if len(result) == EVIDENCE_LIMIT:
            break
    return result


def build_visit_catchup(store, since, as_of, window, *, analyze=False):
    publications, observations = archive_rows(store, since, as_of)
    evidence = select_rows(publications, observations, since, as_of)
    answer = None
    if analyze:
        answer = research.synthesize(store, "visit_catchup",
            "Give a short catch-up on the most significant developments in the supplied reports. "
            "Treat each publication date as context. Do not infer when a development happened or was indexed.",
            evidence, cacheable=True)
    return {"since": since.isoformat(), "as_of": as_of.isoformat(), "window": window,
            "evidence": evidence, "answer": answer, "notice": NOTICE}
