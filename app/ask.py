"""Archive-wide, cited technology questions. Reads only retained public evidence."""

import hashlib
import json
import logging
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError

from app import guardrails, research
from app.article_language import excerpt_language
from app.cache import Cache
from app.coverage import TOPICS
from app.launch_store import get_store
from app.story_groups import distinct_stories

router = APIRouter()
logger = logging.getLogger(__name__)
_cache = Cache("ask-informa-v1")


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    question: str = Field(max_length=guardrails.MAX_QUESTION)
    topic: str = Field(default="all", max_length=64)
    days: int = Field(default=7, ge=1, le=30)

    @field_validator("topic")
    @classmethod
    def check_topic(cls, value: str) -> str:
        if value != "all" and value not in TOPICS:
            raise ValueError("Choose a supported topic.")
        return value


def key_for(store, body: AskRequest) -> str:
    scope = json.dumps(
        [
            store.engine.url.host,
            store.engine.url.database,
            research.route_model("analyze"),
            body.question,
            body.topic,
            body.days,
        ]
    )
    return hashlib.sha256(scope.encode()).hexdigest()


def english_excerpt(row: dict) -> bool:
    if row["summary_basis"] != "publisher_excerpt":
        return False
    language = excerpt_language(row["cleanSummary"])
    # English feeds sometimes contain product-name headlines misclassified by the
    # detector. Prefer a confidently English excerpt over the short headline.
    return language == "en" or (language == "und" and row["language"] == "en")


def retrieve(store, body: AskRequest) -> tuple[list[dict], str]:
    hours = body.days * 24
    filters = {"topic": body.topic, "language": "en"}
    lexical = research.lexical_results(store, body.question, hours, filters)
    try:
        semantic, _ = research.vector_results(store, body.question, hours, filters)
    except SQLAlchemyError as error:
        logger.warning("ask_vectors_unavailable type=%s", type(error).__name__)
        semantic = []
    ranked = research.select_evidence(
        lexical, semantic, limit=24, question=body.question
    )
    records = [
        research.evidence_record(row)
        for row in distinct_stories(ranked)
        if english_excerpt(row)
    ]
    return records[:8], "hybrid" if semantic else "keyword"


def ask_archive(store, body: AskRequest) -> dict:
    if reason := guardrails.rejection(body.question):
        return {
            **guardrails.outcome("refused", reason),
            "retrieved_count": 0,
            "cached": False,
        }
    key = key_for(store, body)
    with _cache.key_lock(key):
        if (value := _cache.get(key)[0]) is not None:
            return {**value, "cached": True}
        records, retrieval = retrieve(store, body)
        answer = research.synthesize(
            store, "analyze", body.question, records, guarded=True
        )
        checked = answer.get("guardrails") or guardrails.outcome(
            "insufficient",
            answer=answer.get("limitations") or guardrails.INSUFFICIENT,
        )
        result = {
            **checked,
            "retrieved_count": len(records),
            "retrieval": retrieval,
            "cached": False,
        }
        if answer["status"] in {"unavailable", "budget_limited"}:
            result["reason"] = answer["status"]
        if (
            checked["status"] == "answered"
            or not records
            or answer.get("evidence_inconclusive")
        ):
            _cache.put(key, result, ttl=research.ANSWER_CACHE_SECONDS)
        return result


def answer_request(body: AskRequest, request: Request) -> dict:
    from app.server import admit_expensive

    if reason := guardrails.rejection(body.question):
        return {
            **guardrails.outcome("refused", reason),
            "retrieved_count": 0,
            "cached": False,
        }
    store = get_store()
    if not store:
        raise HTTPException(503, "The archive is temporarily unavailable.")
    # Both transports and the existing story-question route share the same allowance.
    admit_expensive(store, request, "source-conversation", 10, 600)
    return ask_archive(store, body)


@router.post("/api/ask")
def ask_informa(body: AskRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return answer_request(body, request)
