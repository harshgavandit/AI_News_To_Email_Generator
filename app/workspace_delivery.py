"""Dispatch a stored brief to a reader-supplied Slack or Teams webhook."""
import hashlib
import re
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app import public_mail
from app.brand import BRIEF_SUBJECT
from app.launch_store import get_store
from app.news import canonical_url
from app.web_digest import markdown_text, story_attribution

router = APIRouter(prefix="/api/deliver")


class WebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{24,80}$")]
    url: Annotated[str, Field(min_length=15, max_length=2048)]


def webhook_provider(url: str) -> str:
    if any(char.isspace() or ord(char) < 32 for char in url) or "\\" in url:
        raise ValueError("Invalid webhook URL.")
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443) or parts.fragment:
        raise ValueError("Use a secure Slack or Microsoft Teams webhook URL.")
    if host == "hooks.slack.com" and not parts.query and re.fullmatch(r"/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", parts.path):
        return "slack"
    if re.fullmatch(r"[a-z0-9.-]+\.webhook\.office\.com", host) and re.fullmatch(r"/webhook(?:b2)?/[A-Za-z0-9@_/-]+/IncomingWebhook/[A-Za-z0-9_/-]+", parts.path):
        return "teams"
    if re.fullmatch(r"[a-z0-9.-]+\.(?:logic\.azure\.com|environment\.api\.powerplatform\.com)", host):
        query = parse_qs(parts.query, max_num_fields=12)
        path = r"/(?:powerautomate/automations/direct/)?workflows/[a-zA-Z0-9_-]+/triggers/manual/(?:paths/)?invoke"
        if re.fullmatch(path, parts.path) and len(query.get("sig", [])) == 1:
            return "teams"
    raise ValueError("Paste a Slack Incoming Webhook or a Microsoft Teams Workflows webhook.")


def message_payload(digest: dict, provider: str) -> dict:
    intro = digest.get("introduction", {}).get("introduction", "")[:600]
    rows = []
    for story in digest.get("articles", [])[:10]:
        try:
            url = canonical_url(story["url"])
        except (KeyError, ValueError, TypeError):
            continue
        title = story.get("title", "Story")[:280]
        publisher = story_attribution(story)[:180]
        summary = story.get("summary", "")[:500]
        rows.append((title, publisher, summary, url))

    if provider == "slack":
        blocks = [{"type": "header", "text": {"type": "plain_text", "text": BRIEF_SUBJECT}}]
        if intro:
            blocks.append({"type": "section", "text": {"type": "plain_text", "text": intro}})
        for title, publisher, summary, url in rows:
            blocks.append({"type": "section", "text": {"type": "plain_text", "text": f"{title}\n{publisher}\n{summary}"},
                           "accessory": {"type": "button", "text": {"type": "plain_text", "text": "Read source"},
                                         "url": url, "action_id": "read_source"}})
        return {"text": BRIEF_SUBJECT, "blocks": blocks, "unfurl_links": False, "unfurl_media": False}

    blocks = [{"type": "TextBlock", "text": BRIEF_SUBJECT, "weight": "Bolder", "size": "Large"}]
    if intro:
        blocks.append({"type": "TextBlock", "text": markdown_text(intro), "wrap": True})
    for title, publisher, summary, url in rows:
        blocks.extend([
            {"type": "TextBlock", "text": markdown_text(title), "weight": "Bolder", "wrap": True, "separator": True},
            {"type": "TextBlock", "text": f"{markdown_text(publisher)}\n{markdown_text(summary)}", "wrap": True},
            {"type": "ActionSet", "actions": [{"type": "Action.OpenUrl", "title": "Read source", "url": url}]},
        ])
    card = {"type": "AdaptiveCard", "version": "1.2", "body": blocks}
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


@router.post("/webhook")
def dispatch(body: WebhookRequest, request: Request):
    try:
        provider = webhook_provider(body.url)
    except ValueError:
        raise HTTPException(422, "Enter a valid HTTPS Slack or Teams Workflows webhook URL.") from None
    recipient = public_mail.verified_recipient(request)
    if not recipient:
        raise HTTPException(401, "Verify your inbox before sending to a workspace.")
    store = get_store()
    if not store:
        raise HTTPException(503, "Workspace delivery is temporarily unavailable.")
    digest = store.get_preview(body.preview_id)
    if not digest:
        raise HTTPException(404, "This preview expired. Generate a new brief.")
    destination = hashlib.sha256(body.url.encode()).hexdigest()
    identity = public_mail.digest_key(f"webhook:{destination}:{body.preview_id}")
    status, accepted = store.reserve_delivery(identity, [], windows=[
        (f"dispatch-ip:{public_mail.address_key(request)}", 3600, 5), (f"webhook:{destination}", 3600, 5),
    ])
    if status == "limited":
        raise HTTPException(429, "Workspace delivery is limited to five sends per hour.",
                            headers={"Retry-After": str(accepted)})
    if accepted:
        return {"status": "accepted", "message": "Your workspace accepted the brief."}
    if status != "new":
        raise HTTPException(409, "There is already an attempt for this brief. Check the workspace before retrying.")
    try:
        with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", body.url, json=message_payload(digest, provider)) as response:
                response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(502, "The workspace did not confirm the brief. Check the webhook and channel.") from None
    store.record_delivery(identity, provider)
    return {"status": "accepted", "message": "Your workspace accepted the brief."}
