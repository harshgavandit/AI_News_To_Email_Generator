"""Private projects, collaborators, and revocable snapshots backed by the archive."""
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, Float, Index, String, Table, Text, delete, func, inspect, select, update

from app import monitoring, research, technology
from app.coverage import public_article
from app.discovery import search_terms
from app.launch_store import schema

projects = Table("brief_research_projects", schema,
    Column("id", String(32), primary_key=True), Column("owner", String(64), nullable=False, index=True),
    Column("question", Text, nullable=False), Column("keywords", Text, nullable=False),
    Column("technology", String(32), nullable=False), Column("created", Float, nullable=False))
members = Table("brief_research_members", schema,
    Column("project_id", String(32), primary_key=True), Column("profile_id", String(64), primary_key=True, index=True))
items = Table("brief_research_items", schema,
    Column("project_id", String(32), primary_key=True), Column("article_id", String(40), primary_key=True),
    Column("note", Text, nullable=False), Column("added", Float, nullable=False))
invites = Table("brief_research_invites", schema,
    Column("digest", String(64), primary_key=True), Column("project_id", String(32), nullable=False, unique=True),
    Column("expires", Float, nullable=False))
briefs = Table("brief_research_briefs", schema,
    Column("id", String(43), primary_key=True), Column("project_id", String(32), nullable=False),
    Column("created", Float, nullable=False), Column("expires", Float, nullable=False, index=True),
    Column("payload", Text, nullable=False))
Index("brief_research_briefs_project", briefs.c.project_id, briefs.c.created)
TABLES = (projects, members, items, invites, briefs)
ProjectTechnology = Literal["", *technology.TECHNOLOGIES]
router = APIRouter(prefix="/api/intelligence/inbox/projects")
public_router = APIRouter(prefix="/api/intelligence/briefs")


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=5, max_length=240)
    keywords: str = Field(min_length=2, max_length=100)
    technology: ProjectTechnology = ""

    @field_validator("keywords")
    @classmethod
    def meaningful(cls, value):
        if not search_terms(value):
            raise ValueError("Enter words to search for.")
        return value


class ProjectSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    article_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    note: str | None = Field(default=None, max_length=1500)


class BriefInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience: Literal["engineering", "security", "leadership"] = "engineering"
    language: Literal[tuple(research.OUTPUT_LANGUAGES)] = "en"
    window: Literal["week", "all"] = "all"


class LinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[a-zA-Z0-9_-]{43}$")


def ready(store):
    if not getattr(store, "_projects_ready", False):
        check = inspect(store.engine)
        store._projects_ready = all(check.has_table(table.name) for table in TABLES)
    return store._projects_ready


def session(request, response, *, write=False, limit=None):
    from app.server import admit_expensive

    if write:
        monitoring.protect_write(request)
    response.headers["Cache-Control"] = "private, no-store"
    store = monitoring.configured_store()
    if not ready(store):
        raise HTTPException(503, "Research projects are being prepared.")
    ident = monitoring.profile_id(request)
    with store.engine.connect() as conn:
        if not monitoring.active_profile(conn, ident, time.time()):
            raise HTTPException(401, "Enable background monitoring to use research projects.")
    if limit:
        admit_expensive(store, request, limit, 12 if limit != "project-brief" else 5, 600)
    return store, ident


def access(conn, ident, profile, *, lock=False, owner_only=False):
    if not monitoring.active_profile(conn, profile, time.time(), lock=lock):
        raise HTTPException(401, "Enable background monitoring to use research projects.")
    stmt = select(projects).join(monitoring.monitor_profiles,
        projects.c.owner == monitoring.monitor_profiles.c.id).where(projects.c.id == ident,
        monitoring.monitor_profiles.c.expires > time.time())
    found = conn.execute(stmt.with_for_update(of=projects) if lock else stmt).mappings().first()
    allowed = found and (found["owner"] == profile or (not owner_only and conn.scalar(select(members.c.profile_id).where(
        members.c.project_id == ident, members.c.profile_id == profile))))
    if not allowed:
        raise HTTPException(404, "This research project is unavailable.")
    return found


def project_view(row, profile):
    return {key: row[key] for key in ("id", "question", "keywords", "technology", "created")} | {"owner": row["owner"] == profile}


@router.get("")
def list_projects(request: Request, response: Response):
    store, profile = session(request, response)
    from sqlalchemy import or_
    with store.engine.connect() as conn:
        invited = select(members.c.project_id).where(members.c.profile_id == profile)
        rows = conn.execute(select(projects).join(monitoring.monitor_profiles,
            projects.c.owner == monitoring.monitor_profiles.c.id).where(monitoring.monitor_profiles.c.expires > time.time(),
            or_(projects.c.owner == profile, projects.c.id.in_(invited))).order_by(projects.c.created.desc()).limit(40)).mappings()
        return {"projects": [project_view(row, profile) for row in rows]}


@router.post("", status_code=201)
def create_project(body: ProjectInput, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    row = {"id": secrets.token_hex(16), "owner": profile, "created": time.time(), **body.model_dump()}
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        if not monitoring.active_profile(conn, profile, time.time(), lock=True):
            raise HTTPException(401, "Enable background monitoring to use research projects.")
        if conn.scalar(select(func.count()).select_from(projects).where(projects.c.owner == profile)) >= 10:
            raise HTTPException(422, "Delete a project before creating another. Each owner can have ten projects.")
        conn.execute(projects.insert().values(row))
    return project_view(row, profile)


def evidence_for(store, ids):
    return {row["id"]: research.evidence_record(public_article(row)) for row in store.pinned_articles(ids)}


@router.get("/{ident}")
def get_project(ident: str, request: Request, response: Response):
    store, profile = session(request, response)
    with store.engine.connect() as conn:
        project = project_view(access(conn, ident, profile), profile)
        saved = conn.execute(select(items).where(items.c.project_id == ident).order_by(items.c.added.desc())).mappings().all()
        links = conn.execute(select(briefs.c.id, briefs.c.created, briefs.c.expires).where(
            briefs.c.project_id == ident, briefs.c.expires > time.time()).order_by(briefs.c.created.desc())).mappings().all()
    evidence = evidence_for(store, [row["article_id"] for row in saved])
    return {**project, "sources": [{"id": row["article_id"], "note": row["note"], "evidence": evidence.get(row["article_id"])}
                                  for row in saved], "briefs": [dict(row) for row in links]}


@router.get("/{ident}/discover")
def discover(ident: str, request: Request, response: Response):
    store, profile = session(request, response, limit="project-discovery")
    with store.engine.connect() as conn:
        project = dict(access(conn, ident, profile))
        saved = set(conn.scalars(select(items.c.article_id).where(items.c.project_id == ident)))
    terms = search_terms(project["keywords"])
    if project["technology"]:
        rows = technology.eligible_rows(store, project["technology"], 720)
        matches = [row for row in rows if all(research.contains_term(
            research.search_text(row["title"] + " " + row["excerpt"]), term) for term in terms)]
    else:
        rows = research.lexical_results(store, project["keywords"], 720, {}, strict=True)
        matches = [research.evidence_record(row) for row in research.select_evidence(rows, [], limit=24)]
    return {"evidence": [row for row in matches if row["id"] not in saved][:20]}


@router.put("/{ident}/sources")
def save_source(ident: str, body: ProjectSource, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    if not store.pinned_articles([body.article_id]):
        raise HTTPException(404, "This source is unavailable in the archive.")
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        access(conn, ident, profile, lock=True)
        exists = conn.scalar(select(items.c.article_id).where(items.c.project_id == ident, items.c.article_id == body.article_id))
        count = conn.scalar(select(func.count()).select_from(items).where(items.c.project_id == ident))
        if not exists and count >= 24:
            raise HTTPException(422, "A project can hold up to 24 source records.")
        stmt = store.insert(items).values(project_id=ident, article_id=body.article_id, note=body.note or "", added=time.time())
        if body.note is None:
            conn.execute(stmt.on_conflict_do_nothing())
        else:
            conn.execute(stmt.on_conflict_do_update(index_elements=[items.c.project_id, items.c.article_id],
                set_={"note": stmt.excluded.note}))
    return {"saved": True}


@router.delete("/{ident}/sources/{article_id}")
def remove_source(ident: str, article_id: str, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        access(conn, ident, profile, lock=True)
        conn.execute(delete(items).where(items.c.project_id == ident, items.c.article_id == article_id))
    return {"removed": True}


@router.post("/{ident}/invite")
def invite(ident: str, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    token = secrets.token_urlsafe(32)
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        access(conn, ident, profile, lock=True, owner_only=True)
        conn.execute(delete(invites).where(invites.c.project_id == ident))
        conn.execute(invites.insert().values(digest=hashlib.sha256(token.encode()).hexdigest(),
            project_id=ident, expires=time.time() + 86400))
    return {"token": token}


@router.post("/join", status_code=201)
def join(body: LinkInput, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        invitation = conn.execute(select(invites).where(invites.c.digest == digest,
            invites.c.expires > time.time())).mappings().first()
        if not invitation:
            raise HTTPException(404, "This invitation was used or expired.")
        ident = invitation["project_id"]
        project = conn.execute(select(projects).where(projects.c.id == ident).with_for_update()).mappings().first()
        if not project or project["owner"] == profile or not monitoring.active_profile(conn, project["owner"], time.time()):
            raise HTTPException(422, "Open the invitation in another enabled browser.")
        if not monitoring.active_profile(conn, profile, time.time()):
            raise HTTPException(401, "Enable background monitoring to accept the invitation.")
        used = conn.execute(delete(invites).where(invites.c.digest == digest)).rowcount
        if not used:
            raise HTTPException(404, "This invitation was already used.")
        if conn.scalar(select(func.count()).select_from(members).where(members.c.project_id == ident)) >= 12:
            raise HTTPException(422, "This project has reached its collaborator limit.")
        if conn.scalar(select(func.count()).select_from(members).where(members.c.profile_id == profile)) >= 30:
            raise HTTPException(422, "This browser has reached its shared project limit.")
        conn.execute(store.insert(members).values(project_id=ident, profile_id=profile).on_conflict_do_nothing())
    return {"id": ident}


@router.delete("/{ident}/collaborators")
def revoke_collaboration(ident: str, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        access(conn, ident, profile, lock=True, owner_only=True)
        conn.execute(delete(invites).where(invites.c.project_id == ident))
        conn.execute(delete(members).where(members.c.project_id == ident))
    return {"revoked": True}


def remove_projects(conn, ids):
    for table in (briefs, invites, members, items):
        conn.execute(delete(table).where(table.c.project_id.in_(ids)))
    conn.execute(delete(projects).where(projects.c.id.in_(ids)))


def remove_profiles(conn, ids):
    if inspect(conn).has_table(projects.name):
        owned = conn.scalars(select(projects.c.id).where(projects.c.owner.in_(ids)).with_for_update()).all()
        remove_projects(conn, owned)
        conn.execute(delete(members).where(members.c.profile_id.in_(ids)))


@router.delete("/{ident}")
def delete_project(ident: str, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        access(conn, ident, profile, lock=True, owner_only=True)
        remove_projects(conn, [ident])
    return {"deleted": True}


@router.post("/{ident}/brief", status_code=201)
def create_brief(ident: str, body: BriefInput, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-brief")
    with store.engine.connect() as conn:
        project = dict(access(conn, ident, profile))
        if conn.scalar(select(func.count()).select_from(briefs).where(
            briefs.c.project_id == ident, briefs.c.expires > time.time())) >= 10:
            raise HTTPException(422, "Revoke an older link before creating another brief.")
        ids = list(conn.scalars(select(items.c.article_id).where(items.c.project_id == ident).order_by(items.c.added.desc())))
    live = evidence_for(store, ids)
    evidence = [live[key] for key in ids if key in live]
    if body.window == "week":
        cutoff = time.time() - 7 * 86400
        evidence = [row for row in evidence if datetime.fromisoformat(row["published_at"]).timestamp() >= cutoff]
    if not evidence:
        raise HTTPException(422, "Save available sources in the selected period before preparing a brief.")
    # Project notes are private. Shared snapshots contain the project question and public sources.
    question = f"Audience: {body.audience}. Research question: {project['question']}"
    answer = research.synthesize(store, "project", question, evidence, language=body.language)
    now = time.time()
    payload = {"question": project["question"], "audience": body.audience, "language": body.language,
               "answer": answer, "evidence": evidence, "period": "Past 7 days" if body.window == "week" else "Saved project sources"}
    token = secrets.token_urlsafe(32)
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        access(conn, ident, profile, lock=True)
        conn.execute(delete(briefs).where(briefs.c.project_id == ident, briefs.c.expires <= now))
        if conn.scalar(select(func.count()).select_from(briefs).where(briefs.c.project_id == ident)) >= 10:
            raise HTTPException(422, "Revoke an older link before creating another brief.")
        conn.execute(briefs.insert().values(id=token, project_id=ident, created=now,
            expires=now + 90 * 86400, payload=json.dumps(payload, ensure_ascii=False)))
    return {"id": token, "created": now, **payload}


@router.delete("/{ident}/briefs/{token}")
def revoke_brief(ident: str, token: str, request: Request, response: Response):
    store, profile = session(request, response, write=True, limit="project-write")
    with store.engine.begin() as conn:
        monitoring.begin_write(conn)
        access(conn, ident, profile, lock=True)
        conn.execute(delete(briefs).where(briefs.c.project_id == ident, briefs.c.id == token))
    return {"revoked": True}


@public_router.post("/open")
def read_brief(body: LinkInput, request: Request, response: Response):
    from app.server import admit_expensive
    store = monitoring.configured_store()
    if not ready(store):
        raise HTTPException(503, "Shared briefs are being prepared.")
    admit_expensive(store, request, "shared-brief-read", 40, 600)
    response.headers["Cache-Control"] = "private, no-store"
    with store.engine.connect() as conn:
        row = conn.execute(select(briefs).join(projects, briefs.c.project_id == projects.c.id)
            .join(monitoring.monitor_profiles, projects.c.owner == monitoring.monitor_profiles.c.id).where(
            briefs.c.id == body.token, briefs.c.expires > time.time(), monitoring.monitor_profiles.c.expires > time.time())).mappings().first()
    if not row:
        raise HTTPException(404, "This shared brief was revoked or expired.")
    saved = json.loads(row["payload"])
    live = evidence_for(store, [source["id"] for source in saved["evidence"]])
    # Hide claims whose original evidence was revised or made unavailable after this edition.
    unchanged = {source["id"] for source in saved["evidence"] if live.get(source["id"]) == source}
    answer = saved["answer"]
    claims = [claim for claim in answer["claims"] if set(claim["source_ids"]) <= unchanged]
    changed = len(unchanged) != len(saved["evidence"])
    limitations = "The retained sources changed after publication. Review the current reading list." if changed else answer["limitations"]
    return {**saved, "created": row["created"], "evidence": [live[source["id"]] for source in saved["evidence"] if source["id"] in live],
            "answer": {**answer, "claims": claims, "limitations": limitations,
                       "status": "evidence_changed" if changed and not claims else answer["status"]},
            "evidence_changed": changed}
