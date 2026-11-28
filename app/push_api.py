"""Device alerts: turn Web Push on or off for this browser and keep its follow list current."""
from typing import Annotated
import zoneinfo

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import ai_insights, push_alerts
from app.launch_store import get_store

router = APIRouter()


class SubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="ignore")
    p256dh: str = Field(max_length=120)
    auth: str = Field(max_length=40)


class BrowserSubscription(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: str = Field(max_length=1024)
    keys: SubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def push_service(cls, value):
        if not push_alerts.valid_endpoint(value):
            raise ValueError("This browser's push service is not supported.")
        return value


class AlertSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_per_day: Annotated[int, Field(ge=1, le=5)] = 3
    quiet_hours: bool = True
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value):
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            return "UTC"
        return value


class AlertSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription: BrowserSubscription
    profile: ai_insights.RadarProfile
    settings: AlertSettings = Field(default_factory=AlertSettings)


class EndpointOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=1024)


class Rotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_endpoint: str = Field(max_length=1024)
    subscription: BrowserSubscription


FOLLOW_FIELDS = ("followed_events", "followed_technologies", "stack", "topics", "interests")


def follow_profile(profile: ai_insights.RadarProfile) -> dict:
    """Keep only what selects alerts; reading preferences such as language stay in the browser."""
    data = profile.model_dump()
    return {**{field: data[field] for field in FOLLOW_FIELDS},
            "feedback": {"companies": data["feedback"]["companies"], "muted_topics": data["feedback"]["muted_topics"]}}


def follow_count(profile: dict) -> int:
    return sum(len(profile[field]) for field in FOLLOW_FIELDS) + len(profile["feedback"]["companies"])


def same_origin(request: Request):
    from app.monitoring import protect_write
    try:
        protect_write(request)
    except HTTPException:
        raise HTTPException(403, "Manage alerts from Informa AI in this browser.") from None


def store_or_503():
    store = get_store()
    if not store:
        raise HTTPException(503, "Alerts are unavailable right now.")
    return store


def limit(request: Request, action: str, count: int):
    from app.server import rate_limit  # Imported here: the server module includes this router.
    rate_limit(request, action, count)


@router.get("/api/push/config")
def push_config(response: Response):
    key = push_alerts.vapid_key()
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"enabled": key is not None, "public_key": push_alerts.public_key(key) if key else None,
            "max_per_day": [1, 3, 5], "quiet_hours": "22:00–07:00"}


@router.put("/api/push/subscription")
def save_subscription(body: AlertSubscription, request: Request):
    same_origin(request)
    limit(request, "push-save", 30)
    if not push_alerts.enabled():
        raise HTTPException(503, "Alerts are not available yet.")
    keys = body.subscription.keys
    if not push_alerts.valid_keys(keys.p256dh, keys.auth):
        raise HTTPException(422, "This browser sent an unusable push key. Turn alerts off and on again.")
    profile = follow_profile(body.profile)
    follows = follow_count(profile)
    if not follows:
        raise HTTPException(422, "Follow a story, technology, company or topic first, then turn on alerts.")
    push_alerts.save(store_or_503(), body.subscription.endpoint, keys.p256dh, keys.auth, profile, body.settings.model_dump())
    return {"status": "on", "follows": follows, "settings": body.settings.model_dump()}


@router.put("/api/intelligence/inbox/agent-push")
def save_agent_subscription(body: AlertSubscription, request: Request, response: Response):
    from app import monitoring

    same_origin(request)
    limit(request, "watch-agent-push", 10)
    ident = monitoring.profile_id(request)
    if not ident:
        raise HTTPException(401, "Save a Watch agent watch in this browser first.")
    if not push_alerts.enabled():
        raise HTTPException(503, "Device alerts are not available yet.")
    keys = body.subscription.keys
    if not push_alerts.valid_keys(keys.p256dh, keys.auth):
        raise HTTPException(422, "Turn device alerts off and on again to renew the keys.")
    store = monitoring.configured_store()
    try:
        push_alerts.save(store, body.subscription.endpoint, keys.p256dh, keys.auth,
                         follow_profile(body.profile), body.settings.model_dump(), monitor_id=ident)
    except ValueError:
        raise HTTPException(409, "This device could not be linked. Check that monitoring and push are on in this browser.") from None
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "on", "settings": body.settings.model_dump()}


@router.post("/api/push/subscription/remove", status_code=204)
def remove_subscription(body: EndpointOnly, request: Request):
    same_origin(request)
    limit(request, "push-remove", 30)
    push_alerts.remove(store_or_503(), body.endpoint)
    return Response(status_code=204)


@router.post("/api/push/subscription/rotate", status_code=204)
def rotate_subscription(body: Rotation, request: Request):
    same_origin(request)
    limit(request, "push-rotate", 10)
    keys = body.subscription.keys
    if not push_alerts.valid_keys(keys.p256dh, keys.auth):
        raise HTTPException(422, "Unusable push key.")
    if not push_alerts.rotate(store_or_503(), body.old_endpoint, body.subscription.endpoint, keys.p256dh, keys.auth):
        raise HTTPException(404, "Alerts are not on for this browser.")
    return Response(status_code=204)


@router.post("/api/push/test")
def test_alert(body: EndpointOnly, request: Request):
    same_origin(request)
    limit(request, "push-test", 3)
    row = push_alerts.find(store_or_503(), body.endpoint)
    if not row:
        raise HTTPException(404, "Alerts are not on for this browser.")
    status = push_alerts.deliver(row, {"title": "Alerts are on", "url": "/",
        "body": "You'll hear about new coverage of what you follow, at most a few times a day.", "tag": "informa-test"})
    if status in {404, 410}:
        push_alerts.remove(store_or_503(), body.endpoint)
        raise HTTPException(410, "This browser's alert subscription expired. Turn alerts on again.")
    if not 200 <= status < 300:
        raise HTTPException(502, "The browser's push service did not accept the test. Try again later.")
    return {"status": "sent"}
