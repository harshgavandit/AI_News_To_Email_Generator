"""Public source-grounded AI tools and private verified-inbox radar controls."""
import re
import secrets
import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import ai_insights, event_intelligence, monitoring, public_mail, radar_store, research
from app.coverage import TOPICS, public_article
from app.launch_store import get_store
from app.research import evidence_record

router = APIRouter()


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=2, max_length=600)


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=320)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=8)
    context_ids: list[str] = Field(default_factory=list, max_length=8)
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
def developments(response: Response, hours: Annotated[int, Query(ge=24, le=720)] = 168,
                 topic: str = "all", limit: Annotated[int, Query(ge=1, le=80)] = 24):
    if topic not in ("all", *TOPICS):
        raise HTTPException(422, "Choose a supported topic.")
    store = archive()
    response.headers["Cache-Control"] = "public, max-age=30"
    return {"events": event_intelligence.catalog(store, hours=hours, limit=limit, topic=topic),
            "status": "available" if event_intelligence.ready(store) else "warming",
            "notice": "Related coverage is grouped by source evidence. Grouping does not establish agreement."}


@router.get("/api/intelligence/events/{event_id}")
def development(event_id: str, response: Response):
    result = event_intelligence.timeline(archive(), event_id)
    if not result:
        raise HTTPException(404, "This development is no longer in the retained archive.")
    response.headers["Cache-Control"] = "no-store"
    return result


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
    return {"answer": ai_insights.explain(store, evidence, depth=body.depth, language=body.language),
            "evidence": evidence}


@router.post("/api/intelligence/catchup")
def catch_up(body: ai_insights.CatchupRequest, request: Request, response: Response):
    from app.server import admit_expensive
    store = archive()
    admit_expensive(store, request, "catch-up", 10, 600)
    result = ai_insights.catchup(store, body.profile, body.seen, hours=body.hours)
    if brief := result.pop("brief", None):
        expires, ident = int(time.time()) + 3600, secrets.token_urlsafe(24)
        store.save_preview(ident, brief, expires)
        result["preview"] = {"digest": brief, "expires": expires, "preview_id": ident,
                             "source_basis": result["source_notice"]}
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/api/intelligence/converse")
def converse(body: ConversationRequest, request: Request, response: Response):
    from app.server import admit_expensive
    store = archive()
    admit_expensive(store, request, "source-conversation", 10, 600)
    context_rows = [public_article(row) for row in store.pinned_articles(body.context_ids)] if body.context_ids else []
    previous_questions = [turn.content for turn in body.history if turn.role == "user"][-3:]
    retrieval_query = " ".join([*previous_questions, *(row["title"] for row in context_rows), body.question])
    result = research.research(store, question=body.question, retrieval_question=retrieval_query,
        context_rows=context_rows, mode="analyze", language=body.language,
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
    radar_store.save_profile(store, mailbox, body.model_dump())
    response.headers["Cache-Control"] = "private, no-store"
    return {"profile": body.model_dump(), "notice": "Applies to opted-in morning mail. This does not subscribe your inbox."}


@router.delete("/api/mail/radar")
def delete_inbox_radar(request: Request, response: Response):
    monitoring.protect_write(request)
    radar_store.remove_profile(archive(), private_mailbox(request))
    response.headers["Cache-Control"] = "private, no-store"
    return {"deleted": True, "notice": "Radar preferences and catch-up history were removed. Morning mail settings are unchanged."}
