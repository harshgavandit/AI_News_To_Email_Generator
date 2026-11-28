"""Reader feedback: a short message from any page, and "Was this useful?" on recap and trackers.

Stored: the page path, the kind, the message, an optional reply address and the day. No IP address,
browser details or account. Messages are kept 180 days; only the owner can read them.
"""
from datetime import UTC, datetime
import re
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Column, Float, String, Table, Text, delete, func, inspect, select

from app.launch_store import get_store, schema

router = APIRouter()
feedback_rows = Table("brief_feedback", schema,
    Column("id", String(24), primary_key=True), Column("created", Float, nullable=False, index=True),
    Column("day", String(10), nullable=False), Column("kind", String(16), nullable=False),
    Column("page", String(120), nullable=False), Column("message", Text, nullable=False),
    Column("contact", String(200), nullable=False, default=""))
RETENTION_DAYS = 180
PAGE = re.compile(r"^/[A-Za-z0-9._/-]{0,119}$")
EMAIL = re.compile(r"^[^@\s<>]{1,64}@[^@\s<>]{1,180}\.[A-Za-z]{2,24}$")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["idea", "bug", "praise", "other", "useful", "not_useful", "coverage", "update_yes", "update_no", "ai_answer"] = "other"
    message: str = Field(default="", max_length=2000)
    page: str = Field(default="/", max_length=120)
    contact: str = Field(default="", max_length=200)
    website: str = Field(default="", max_length=200)  # left empty by people; filled by form bots
    question: str = Field(default="", max_length=320)
    story_ids: list[str] = Field(default_factory=list, max_length=10)
    mode: Literal["", "deep"] = ""

    @model_validator(mode="after")
    def validate_report(self):
        if self.kind != "ai_answer":
            if self.question or self.story_ids or self.mode:
                raise ValueError("Story references belong on AI answer reports.")
            return self
        from app.guardrails import rejection
        if self.contact or self.message or rejection(self.question):
            raise ValueError("Report the question without personal or contact information.")
        if not self.story_ids or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", ident) for ident in self.story_ids):
            raise ValueError("Report at least one valid story reference.")
        self.message = self.question + "\nStory IDs: " + ", ".join(dict.fromkeys(self.story_ids))
        if self.mode:
            self.message += "\nMode: " + self.mode
        return self

    @field_validator("page")
    @classmethod
    def site_path(cls, value):
        value = value.split("?", 1)[0].split("#", 1)[0] or "/"
        return value if PAGE.fullmatch(value) else "/"

    @field_validator("message")
    @classmethod
    def plain_text(cls, value):
        return CONTROL.sub("", value)

    @field_validator("contact")
    @classmethod
    def reply_address(cls, value):
        if value and not EMAIL.fullmatch(value):
            raise ValueError("Enter a valid email address, or leave it empty.")
        return value


def ensure(store):
    if getattr(store, "_feedback_ready", False):
        return
    with store.engine.begin() as conn:
        if not inspect(conn).has_table(feedback_rows.name):
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(441108836)")
            feedback_rows.create(conn, checkfirst=True)
    store._feedback_ready = True


def record(store, body: Feedback, now=None):
    ensure(store)
    now = now or time.time()
    with store.engine.begin() as conn:
        conn.execute(feedback_rows.insert().values(
            id=secrets.token_hex(12), created=now, day=datetime.fromtimestamp(now, UTC).date().isoformat(),
            kind=body.kind, page=body.page, message=body.message, contact=body.contact))
        conn.execute(delete(feedback_rows).where(feedback_rows.c.created < now - RETENTION_DAYS * 86400))


def summary(store, since_day):
    """Counts only, for reports that may be visible to others."""
    ensure(store)
    with store.engine.connect() as conn:
        rows = conn.execute(select(feedback_rows.c.kind, feedback_rows.c.page, func.count())
                            .where(feedback_rows.c.day >= since_day)
                            .group_by(feedback_rows.c.kind, feedback_rows.c.page)).all()
    return [{"kind": kind, "page": page, "count": count} for kind, page, count in rows]


@router.post("/api/feedback", status_code=204)
def send_feedback(body: Feedback, request: Request):
    from app.monitoring import protect_write
    from app.server import rate_limit
    try:
        protect_write(request)
    except HTTPException:
        raise HTTPException(403, "Send feedback from the Informa AI site.") from None
    rate_limit(request, "feedback", 6)
    if body.website:
        return Response(status_code=204)  # quietly drop bot submissions
    if body.kind not in {"useful", "not_useful", "update_yes", "update_no"} and len(body.message) < 3:
        raise HTTPException(422, "Write a few words so we know what to fix or build.")
    store = get_store()
    if not store:
        raise HTTPException(503, "Feedback can't be saved right now. Try again later.")
    record(store, body)
    return Response(status_code=204)


@router.get("/api/admin/feedback")
def read_feedback(authorization: str | None = Header(default=None),
                  days: int = Query(default=30, ge=1, le=RETENTION_DAYS), kind: str = Query(default="all", max_length=16)):
    from app.server import require_owner
    require_owner(authorization, detail="Enter a valid owner access key to read feedback.")
    store = get_store()
    if not store:
        raise HTTPException(503, "The archive is unavailable.")
    ensure(store)
    since = time.time() - days * 86400
    statement = select(feedback_rows).where(feedback_rows.c.created >= since)
    if kind != "all":
        statement = statement.where(feedback_rows.c.kind == kind)
    with store.engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(statement.order_by(feedback_rows.c.created.desc()).limit(500)).mappings()]
    for row in rows:
        row["created"] = datetime.fromtimestamp(row["created"], UTC).isoformat(timespec="seconds")
    from app.editor_store import pending_count
    return {"days": days, "count": len(rows), "feedback": rows, "editor_pending": pending_count(store),
            "editor_url": "/admin-editor.html"}
