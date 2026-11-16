"""Verified-inbox reading permissions with explicit, owner-reviewed publication.

Submissions never become public automatically. No submitted URL is fetched.
"""
import hmac
import json
import secrets
import time
from typing import Annotated, Literal

from bs4 import BeautifulSoup, Comment
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
import markdown
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update, tuple_

from app import public_mail
from app.article_metadata import public_link
from app.launch_store import articles, contributions, get_store, reading_permissions
from app.sanitation import sanitize_text

router = APIRouter()
TERMS_VERSION = "reading-permission-2026-11-16-v1"
GRANT = ("I own the rights to this text or have authority to grant permission. I give Informa AI non-exclusive permission "
         "to display this submitted text and generate source-attributed summaries until I withdraw it. "
         "I understand that publication requires editorial review and that my verified email is visible only to the owner.")
ALLOWED_TAGS = {"p", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code", "em", "strong",
                "a", "hr", "br", "table", "thead", "tbody", "tr", "th", "td", "del"}


def render_body(value):
    """Keep readable Markdown structure, safe links and code; strip active HTML and remote assets."""
    soup = BeautifulSoup(markdown.markdown(value, extensions=["fenced_code", "tables"]), "html.parser")
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for tag in soup.find_all(["script", "style", "iframe", "object", "embed", "svg", "math", "form", "input", "button",
                               "img", "video", "audio", "source", "base", "meta", "link"]):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        href = public_link(tag.get("href")) if tag.name == "a" else ""
        tag.attrs = {}
        if href:
            tag.attrs = {"href": href, "target": "_blank", "rel": "noopener noreferrer"}
    return str(soup)


def access_descriptor(permission):
    return {"mode": "full_text", "label": "Full article · with permission", "source_required": False,
            "basis": "rights_holder_permission", "approved_at": permission["approved_at"],
            "attribution": permission["author_name"]}


def annotate_reading(store, rows, *, include_body=False):
    if not rows:
        return rows
    store.ensure_syndication_schema()
    ids = [row["id"] for row in rows]
    columns = list(reading_permissions.c) if include_body else [reading_permissions.c[key] for key in
        ("article_id", "article_url", "author_name", "approved_at")]
    with store.engine.connect() as conn:
        permitted = {row["article_id"]: row for row in conn.execute(select(*columns).where(
            reading_permissions.c.article_id.in_(ids), reading_permissions.c.active.is_(True))).mappings()}
    result = []
    for row in rows:
        article = dict(row)
        permission = permitted.get(article["id"])
        if permission and hmac.compare_digest(permission["article_url"].encode(), article["url"].encode()):
            article["_reading_access"] = access_descriptor(permission)
            if include_body:
                rendered = render_body(permission["body_markdown"])
                article["_reading_content"] = {"html": rendered,
                    "text": BeautifulSoup(rendered, "html.parser").get_text("\n"),
                    "attribution": permission["author_name"]}
        result.append(article)
    return result


def require_contributor(request):
    email = public_mail.verified_recipient(request)
    if not email:
        raise HTTPException(401, "Verify your inbox before managing reading permissions.")
    store = public_mail.required_store()
    store.ensure_syndication_schema()
    return store, email, public_mail.digest_key("contributor:" + email)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    author_name: str = Field(min_length=2, max_length=140)
    body_markdown: str = Field(min_length=200, max_length=30000)
    permission_evidence: str = Field(min_length=30, max_length=2000)
    grant_permission: Literal[True]
    terms_version: Literal[TERMS_VERSION]

    @field_validator("author_name", "permission_evidence", mode="before")
    @classmethod
    def clean_labels(cls, value, info):
        if not isinstance(value, str):
            return value
        return sanitize_text(value, 140).strip() if info.field_name == "author_name" else value.strip()

    @field_validator("body_markdown")
    @classmethod
    def bounded_body(cls, value):
        if len(value.encode()) > 60000:
            raise ValueError("Keep the submitted text below 60 KB.")
        rendered = render_body(value)
        if len(BeautifulSoup(rendered, "html.parser").get_text(" ").strip()) < 200:
            raise ValueError("Include at least 200 characters of readable article text.")
        return value


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject", "revoke"]
    note: str = Field(min_length=10, max_length=1000)
    permission_verified: bool = False

    @field_validator("note", mode="before")
    @classmethod
    def meaningful_note(cls, value):
        return value.strip() if isinstance(value, str) else value


def history(row, action, actor, note=""):
    events = json.loads(row["events"]) if row else []
    return json.dumps([*events, {"action": action, "actor": actor, "at": time.time(), "note": note}])


def submission_record(row, *, owner=False, include_body=False):
    keys = ("id", "article_id", "article_url", "author_name", "permission_evidence", "terms_version",
            "state", "created", "updated", "review_note")
    return {**{key: row[key] for key in keys}, **({"verified_email": row["email"]} if owner else {}),
            **({"body_markdown": row["body_markdown"], "preview_html": render_body(row["body_markdown"]),
                "events": json.loads(row["events"])} if include_body else {})}


@router.get("/api/mail/contributions/config")
def contribution_config(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    config = public_mail.config(request)
    return {**config, "terms_version": TERMS_VERSION, "permission_statement": GRANT}


@router.get("/api/mail/contributions")
def own_contributions(request: Request, response: Response):
    store, _, mailbox = require_contributor(request)
    response.headers["Cache-Control"] = "no-store"
    with store.engine.connect() as conn:
        rows = conn.execute(select(contributions).where(contributions.c.mailbox == mailbox)
                            .order_by(contributions.c.created.desc()).limit(50)).mappings()
        return {"submissions": [submission_record(row) for row in rows]}


@router.post("/api/mail/contributions", status_code=201)
def submit(body: Submission, request: Request):
    store, email, mailbox = require_contributor(request)
    if not store.admit([(f"contribute:{mailbox}", public_mail.day(), 3)]):
        raise HTTPException(429, "You can submit up to three reading permissions per day.", headers={"Retry-After": "3600"})
    article = store.article(body.article_id)
    if not article:
        raise HTTPException(404, "Choose an article currently listed in Informa AI.")
    ident, now = secrets.token_hex(16), time.time()
    with store.engine.begin() as conn:
        conn.execute(contributions.insert().values(id=ident, mailbox=mailbox, email=email, article_id=body.article_id,
            article_url=article["url"], author_name=body.author_name.strip(), body_markdown=body.body_markdown,
            permission_evidence=body.permission_evidence.strip(), terms_version=body.terms_version,
            state="pending", created=now, updated=now, events=history(None, "submitted", "contributor", TERMS_VERSION)))
    return {"id": ident, "state": "pending", "message": "Submitted for owner review. Your text is private until approval."}


@router.get("/api/mail/contributions/{ident}")
def own_submission(ident: str, request: Request, response: Response):
    store, _, mailbox = require_contributor(request)
    response.headers["Cache-Control"] = "no-store"
    with store.engine.connect() as conn:
        row = conn.execute(select(contributions).where(contributions.c.id == ident,
                                                       contributions.c.mailbox == mailbox)).mappings().first()
        if not row:
            raise HTTPException(404, "Submission not found.")
        return submission_record(row, include_body=True)


@router.post("/api/mail/contributions/{ident}/withdraw")
def withdraw(ident: str, request: Request):
    store, _, mailbox = require_contributor(request)
    with store.engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        row = conn.execute(select(contributions).where(contributions.c.id == ident,
            contributions.c.mailbox == mailbox).with_for_update()).mappings().first()
        if not row:
            raise HTTPException(404, "Submission not found.")
        if row["state"] == "withdrawn":
            return {"id": ident, "state": "withdrawn"}
        conn.execute(update(contributions).where(contributions.c.id == ident).values(state="withdrawn", updated=time.time(),
            events=history(row, "withdrawn", "contributor")))
        conn.execute(update(reading_permissions).where(reading_permissions.c.submission_id == ident).values(active=False))
    return {"id": ident, "state": "withdrawn"}


def editor_store(authorization):
    from app.server import require_owner
    require_owner(authorization)
    store = get_store()
    if not store:
        raise HTTPException(503, "The article archive is not configured.")
    store.ensure_syndication_schema()
    return store


@router.get("/api/admin/contributions")
def review_queue(response: Response, state: Annotated[str, Query(pattern=r"^(pending|approved|rejected|withdrawn|revoked)$")] = "pending",
                 cursor: Annotated[str | None, Query(pattern=r"^[a-f0-9]{32}$")] = None,
                 authorization: str | None = Header(default=None)):
    store = editor_store(authorization)
    response.headers["Cache-Control"] = "no-store"
    with store.engine.connect() as conn:
        stmt = select(contributions).where(contributions.c.state == state)
        if cursor:
            marker = conn.execute(select(contributions.c.created).where(contributions.c.id == cursor)).first()
            if not marker:
                raise HTTPException(400, "This review page has expired. Reload the queue.")
            stmt = stmt.where(tuple_(contributions.c.created, contributions.c.id) > tuple_(marker.created, cursor))
        rows = conn.execute(stmt.order_by(contributions.c.created, contributions.c.id).limit(11)).mappings().all()
        return {"submissions": [submission_record(row, owner=True) for row in rows[:10]],
                "next_cursor": rows[9]["id"] if len(rows) > 10 else None}


@router.get("/api/admin/contributions/{ident}")
def review_detail(ident: str, response: Response, authorization: str | None = Header(default=None)):
    store = editor_store(authorization)
    response.headers["Cache-Control"] = "no-store"
    with store.engine.connect() as conn:
        row = conn.execute(select(contributions).where(contributions.c.id == ident)).mappings().first()
        if not row:
            raise HTTPException(404, "Submission not found.")
        return submission_record(row, owner=True, include_body=True)


@router.post("/api/admin/contributions/{ident}/review")
def review(ident: str, body: Review, authorization: str | None = Header(default=None)):
    store = editor_store(authorization)
    with store.engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        row = conn.execute(select(contributions).where(contributions.c.id == ident).with_for_update()).mappings().first()
        if not row:
            raise HTTPException(404, "Submission not found.")
        if body.action == "approve":
            if not body.permission_verified:
                raise HTTPException(422, "Verify the rights holder's permission before approving publication.")
            if row["state"] != "pending":
                raise HTTPException(409, "Only a pending submission can be approved.")
            article = conn.execute(store.query(90 * 24).where(articles.c.id == row["article_id"])).mappings().first()
            if not article or article["url"] != row["article_url"]:
                raise HTTPException(409, "The original article is no longer available or has changed.")
            values = dict(article_id=row["article_id"], submission_id=ident, author_name=row["author_name"],
                body_markdown=row["body_markdown"], body_html=render_body(row["body_markdown"]), article_url=row["article_url"],
                active=True, approved_at=time.time())
            stmt = store.insert(reading_permissions).values(**values)
            conn.execute(stmt.on_conflict_do_update(index_elements=[reading_permissions.c.article_id],
                                                   set_={key: value for key, value in values.items() if key != "article_id"}))
            state = "approved"
        elif body.action == "reject":
            if row["state"] != "pending":
                raise HTTPException(409, "Only a pending submission can be rejected.")
            state = "rejected"
        else:
            if row["state"] != "approved":
                raise HTTPException(409, "Only an approved submission can be revoked.")
            conn.execute(update(reading_permissions).where(reading_permissions.c.submission_id == ident).values(active=False))
            state = "revoked"
        conn.execute(update(contributions).where(contributions.c.id == ident)
                     .values(state=state, review_note=body.note, updated=time.time(), events=history(row, state, "owner", body.note)))
    return {"id": ident, "state": state}
