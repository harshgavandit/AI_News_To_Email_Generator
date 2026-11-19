"""Public source-grounded AI tools and private verified-inbox radar controls."""
import re
import secrets
import time
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import (
    ai_insights, event_intelligence, monitoring, personal_impact, public_mail, radar_store,
    reader_freshness, research, stack_intelligence, technology, visit_catchup, watch_rules,
)
from app.coverage import TOPICS, public_article
from app.provenance import source_history
from app.launch_store import get_store
from app.research import evidence_record

router = APIRouter()


class TechnologyQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    hours: Literal[168, 720, 2160] = 720
    question: str = Field(default="", max_length=320)
    language: Literal[tuple(research.OUTPUT_LANGUAGES)] = "en"


@router.get("/api/intelligence/technologies")
def technology_catalog():
    return {"technologies": technology.catalog(), "watch_events": watch_rules.EVENT_LABELS}


@router.post("/api/intelligence/watch-draft")
def draft_watch(body: watch_rules.DraftInput, request: Request):
    from app.server import admit_expensive
    monitoring.protect_write(request)
    store = archive()
    admit_expensive(store, request, "technology-watch-draft", 6, 600)
    if not research.ai_enabled():
        return {"rule": None, "notice": "AI drafting is unavailable. You can still set the filters directly."}
    if not research.reserve(store, "answers", 180, 1500):
        return {"rule": None, "notice": "The daily AI limit was reached. You can still set the filters directly."}
    try:
        rule = watch_rules.draft(body.intent)
    except Exception:
        return {"rule": None, "notice": "A draft could not be prepared. You can still set the filters directly."}
    return {"rule": rule, "notice": "Review the filters before saving." if rule else "The request could not be represented as one rule. Choose the filters directly."}


@router.get("/api/intelligence/technologies/{ident}")
def technology_page(ident: Literal[tuple(technology.TECHNOLOGIES)], hours: int = 720):
    if hours not in (168, 720, 2160):
        raise HTTPException(422, "Choose 7, 30, or 90 days.")
    return {"records": technology.eligible_rows(archive(), ident, hours), "hours": hours}


@router.post("/api/intelligence/technologies/{ident}/ask")
def ask_technology(ident: Literal[tuple(technology.TECHNOLOGIES)], body: TechnologyQuestion, request: Request):
    from app.server import admit_expensive
    store = archive()
    admit_expensive(store, request, "technology-analysis", 8, 600)
    return technology.edition(store, ident, body.hours, body.question, body.language)


@router.get("/api/intelligence/source-history/{article_id}")
def article_history(article_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,40}$")], request: Request):
    from app.server import admit_expensive
    store = archive()
    admit_expensive(store, request, "source-history", 20, 600)
    result = source_history(store, article_id)
    if not result:
        raise HTTPException(404, "This source is unavailable in the retained archive.")
    return result


@router.post("/api/intelligence/personal-impact")
def impact(body: personal_impact.ImpactRequest, request: Request, response: Response):
    from app.server import admit_expensive

    monitoring.protect_write(request)
    store = archive()
    admit_expensive(store, request, "personal-impact", 8, 600)
    row = store.article(body.article_id)
    if not row:
        raise HTTPException(404, "This story is no longer in the archive.")
    rows = [public_article(row)]
    event_id = event_intelligence.development_for_article(store, body.article_id)
    if event_id and (events := event_intelligence.catalog(store, event_ids=[event_id], limit=1)):
        rows.extend(item for item in events[0]["articles"] if item["id"] != body.article_id)
    response.headers["Cache-Control"] = "private, no-store"
    return personal_impact.check(store, body, rows)


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=2, max_length=600)


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=320)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=8)
    context_ids: list[str] = Field(default_factory=list, max_length=8)
    context_only: bool = False
    hours: Literal[24, 168, 720] = 168
    topic: str = "all"
    language: str = "en"

    @field_validator("language")
    @classmethod
    def supported_language(cls, value):
        return ai_insights.RadarProfile.supported_language(value)

    @field_validator("context_ids")
    @classmethod
    def supported_context(cls, values):
        if len(set(values)) != len(values) or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", value) for value in values):
            raise ValueError("Invalid source references.")
        return values

    @field_validator("topic")
    @classmethod
    def supported_topic(cls, value):
        if value not in ("all", *TOPICS):
            raise ValueError("Choose a supported topic.")
        return value


def archive():
    store = get_store()
    if not store:
        raise HTTPException(503, "The persistent intelligence archive is unavailable.")
    return store


@router.get("/api/intelligence/radar/options")
def options():
    return {"roles": ai_insights.ROLES, "depths": ai_insights.DEPTHS,
            "languages": ai_insights.OUTPUT_LANGUAGES, "topics": TOPICS}


@router.get("/api/intelligence/events")
def developments(response: Response, hours: Annotated[int, Query(ge=12, le=2160)] = 168,
                 topic: str = "all", limit: Annotated[int, Query(ge=1, le=80)] = 24,
                 followed: Annotated[str, Query(max_length=1319)] = "",
                 q: Annotated[str, Query(max_length=150)] = ""):
    if topic not in ("all", *TOPICS):
        raise HTTPException(422, "Choose a supported topic.")
    store = archive()
    event_ids = followed.split(",") if followed else []
    if any(not re.fullmatch(r"[a-f0-9]{32}", ident) for ident in event_ids):
        raise HTTPException(422, "Choose valid developments.")
    response.headers["Cache-Control"] = "private, no-store" if event_ids else "public, max-age=30"
    items = event_intelligence.catalog(store, hours=hours, limit=limit, topic=topic, event_ids=event_ids, query=q.strip())
    result = {"events": items, "status": "available" if event_intelligence.ready(store) else "warming",
              "notice": "Related coverage is grouped by source evidence. Grouping does not establish agreement."}
    if q.strip() and not event_ids:
        source_ids = {row.get("source_id") for event in items for row in event["articles"]}
        result["coverage_freshness"] = reader_freshness.coverage_snapshot(store, topics=[topic], source_ids=source_ids)
    return result


@router.get("/api/intelligence/events/{event_id}")
def development(event_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")], response: Response,
                since: Annotated[int | None, Query(ge=1, le=2147483647)] = None):
    store = archive()
    result = event_intelligence.timeline(store, event_id, since=since)
    if not result:
        raise HTTPException(404, "This development is no longer in the retained archive.")
    response.headers["Cache-Control"] = "no-store"
    source_ids = {item["source"].get("source_id") for item in result["entries"]}
    return {**result, "coverage_freshness": reader_freshness.coverage_snapshot(store, source_ids=source_ids, linked_only=True)}


@router.post("/api/intelligence/explain")
def explanation(body: ai_insights.ExplainRequest, request: Request, response: Response):
    from app.server import admit_expensive
    store = archive()
    admit_expensive(store, request, "article-explanation", 10, 600)
    article = store.article(body.article_id)
    if not article:
        raise HTTPException(404, "This article is no longer available.")
    evidence = [evidence_record(public_article(article))]
    response.headers["Cache-Control"] = "private, no-store"
    if body.format == "technical_brief":
        format_id = ai_insights.technical_format(evidence[0].get("coverage"))
        if not format_id:
            raise HTTPException(422, "Technical briefs are available for releases and research publications.")
        return {"answer": ai_insights.technical_brief(store, evidence, format_id, body.language),
                "evidence": evidence, "sections": ai_insights.TECHNICAL_FIELDS[format_id]}
    return {"answer": ai_insights.explain(store, evidence, depth=body.depth, language=body.language),
            "evidence": evidence}


@router.post("/api/intelligence/catchup")
def catch_up(body: ai_insights.CatchupRequest, request: Request, response: Response):
    from app.server import admit_expensive
    store = archive()
    response.headers["Cache-Control"] = "private, no-store"
    if body.summary_only and not event_intelligence.ready(store):
        raise HTTPException(503, "Developments are still being indexed. Try again shortly.")
    admit_expensive(store, request, "home-catch-up" if body.summary_only else "catch-up",
                    30 if body.summary_only else 10, 600)
    result = ai_insights.catchup(store, body.profile, body.seen, hours=body.hours,
                                 since=body.since, allow_generate=not body.summary_only)
    source_ids = {row.get("source_id") for event in result["events"] for row in event["articles"]}
    result["coverage_freshness"] = reader_freshness.coverage_snapshot(store, topics=body.profile.topics, source_ids=source_ids)
    if (brief := result.pop("brief", None)) and not body.summary_only:
        expires, ident = int(time.time()) + 3600, secrets.token_urlsafe(24)
        store.save_preview(ident, brief, expires)
        result["preview"] = {"digest": brief, "expires": expires, "preview_id": ident,
                             "source_basis": result["source_notice"]}
    return result


@router.post("/api/intelligence/visit-catchup")
def catch_up_since_visit(body: visit_catchup.VisitCatchupRequest, request: Request, response: Response):
    from app.server import admit_expensive, rate_limit

    try:
        since, as_of, window = visit_catchup.visit_window(body)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    store = archive()
    if body.analyze:
        monitoring.protect_write(request)
        admit_expensive(store, request, "visit-catchup-analysis", 6, 600)
    else:
        rate_limit(request, "visit-catchup-evidence", 60)
    response.headers["Cache-Control"] = "private, no-store"
    return visit_catchup.build_visit_catchup(store, since, as_of, window, analyze=body.analyze)


@router.post("/api/intelligence/package-check")
def package_check(body: stack_intelligence.PackageCheck, request: Request, response: Response):
    from app.server import admit_expensive
    store = archive()
    admit_expensive(store, request, "package-check", 8, 600)
    try:
        result = stack_intelligence.advisories(store, body)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(502, "The advisory database could not complete this check.") from error
    response.headers["Cache-Control"] = "private, no-store"
    return {**result, "answer": ai_insights.explain(store, result["evidence"], depth="developer",
        prompt=ai_insights.PROMPT + " Explain the published issue and only the mitigation explicitly described in the advisory.")}


@router.post("/api/intelligence/converse")
def converse(body: ConversationRequest, request: Request, response: Response):
    from app.server import admit_expensive
    store = archive()
    admit_expensive(store, request, "source-conversation", 10, 600)
    context_rows = [public_article(row) for row in store.pinned_articles(body.context_ids)] if body.context_ids else []
    if body.context_only and (not context_rows or len(context_rows) != len(body.context_ids)):
        raise HTTPException(404, "This story is no longer available. Reopen it before asking a question.")
    previous_questions = [turn.content for turn in body.history if turn.role == "user"][-3:]
    retrieval_query = " ".join([*previous_questions, *(row["title"] for row in context_rows), body.question])
    result = research.research(store, question=body.question, retrieval_question=retrieval_query,
        context_rows=context_rows, context_only=body.context_only, mode="analyze", language=body.language,
        filters={"hours": body.hours, "topic": body.topic})
    response.headers["Cache-Control"] = "private, no-store"
    return result


def private_mailbox(request):
    recipient = public_mail.verified_recipient(request)
    if not recipient:
        raise HTTPException(401, "Verify your inbox before managing its radar.")
    return public_mail.digest_key("mailbox:" + recipient)


@router.get("/api/mail/radar")
def inbox_radar(request: Request, response: Response):
    mailbox, store = private_mailbox(request), archive()
    response.headers["Cache-Control"] = "private, no-store"
    return {"profile": radar_store.profiles(store, [mailbox]).get(mailbox),
            "seen": radar_store.histories(store, [mailbox]).get(mailbox, {})}


@router.put("/api/mail/radar")
def update_inbox_radar(body: ai_insights.RadarProfile, request: Request, response: Response):
    monitoring.protect_write(request)
    mailbox, store = private_mailbox(request), archive()
    if not radar_store.ready(store):
        raise HTTPException(503, "Radar storage is being prepared. Try again shortly.")
    if body.delivery_mode == "material_updates" and not (
            body.followed_events or body.followed_technologies or body.feedback.companies
            or body.interests or body.stack or body.topics):
        raise HTTPException(422, "Add a followed story, company, technology, or topic before enabling followed updates.")
    radar_store.save_profile(store, mailbox, body.model_dump())
    response.headers["Cache-Control"] = "private, no-store"
    notice = ("Morning mail will include only new or materially changed developments that match your follows. "
              "Mornings without matching updates are skipped." if body.delivery_mode == "material_updates" else
              "Personalized preferences saved. They apply if your inbox is opted into morning mail.")
    return {"profile": body.model_dump(), "notice": notice}


@router.delete("/api/mail/radar")
def delete_inbox_radar(request: Request, response: Response):
    monitoring.protect_write(request)
    radar_store.remove_profile(archive(), private_mailbox(request))
    response.headers["Cache-Control"] = "private, no-store"
    return {"deleted": True, "notice": "Radar preferences and catch-up history were removed. Morning mail settings are unchanged."}
