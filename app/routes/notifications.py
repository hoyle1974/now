"""Push device registration and the Cloud Scheduler / Tasks / Pub/Sub callbacks."""
from __future__ import annotations

import datetime
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import auth, db, models, push, shares, tenant

log = logging.getLogger(__name__)
router = APIRouter()


class SyncCalendarBody(BaseModel):
    calendar_id: str = Field(min_length=1, max_length=64)
    user: str | None = Field(None, max_length=320)
    client_session_id: str | None = Field(None, max_length=64)

@router.post("/push/devices")
def register_push_device(body: push.DeviceRegistration) -> dict:
    """The installed app reports its FCM token and timezone at every launch."""
    if not push.valid_tz(body.tz):
        raise HTTPException(400, "unknown timezone")
    db.upsert_push_device(push.device_id(body.token), body.token, body.tz, body.platform)
    return {"ok": True}

@router.post("/push/devices/unregister")
def unregister_push_device(body: push.TokenOnly) -> dict:
    db.delete_push_device(push.device_id(body.token))
    return {"ok": True}

@router.post("/internal/notify")
def notify() -> dict:
    """Cloud Scheduler tick (OIDC-verified in require_user): send each allowed user's due
    reminders. One job serves everyone; the totals keep the old response shape."""
    now = datetime.datetime.now(datetime.UTC)
    total = {"devices": 0, "sent": 0, "scheduled": 0}
    for email in auth.allowed_emails():
        try:
            with tenant.as_user(email):
                out = push.run_notify(now, send=push.send_fcm)
        except Exception:
            log.exception("digest failed for %s; the others still get theirs", email)
            continue
        for key in total:
            total[key] += out.get(key, 0)
    return total

@router.post("/internal/budget-alert")
def budget_alert(body: push.PubSubEnvelope) -> dict:
    """Pub/Sub push of a Cloud Billing budget notification (OIDC-verified in require_user):
    tell the owner's devices immediately (billing is the owner's business)."""
    with tenant.as_user(auth.owner()):
        return push.run_budget_alert(body.message.data, datetime.datetime.now(datetime.UTC), send=push.send_fcm)

@router.post("/internal/notify-todo")
def notify_todo(body: push.HeadsUp) -> dict:
    """Cloud Tasks delivery for one heads-up (OIDC-verified in require_user). `user` is
    absent on tasks queued before users existed: fall back to the owner rather than crash."""
    user = (body.user or auth.owner()).lower()
    if user not in auth.allowed_emails():
        raise HTTPException(400, "unknown user")
    now = datetime.datetime.now(datetime.UTC)
    partition = body.partition
    if not (partition and partition.startswith("shares/")) and auth.sharing_enabled():
        # Queued before the item was shared or moved: find where it lives now.
        with tenant.as_user(user):
            try:
                gone = db.get_todo(models.TodoId(uuid.UUID(body.todo_id))) is None
            except ValueError:
                gone = False
            if gone:
                partition = shares.locate(body.todo_id) or partition
    if partition and partition.startswith("shares/"):
        # A shared item: everyone who has it in their list hears about it on their devices.
        share = shares.get(partition.split("/", 1)[1])
        if share is None or share.state != "active":
            return {"sent": 0, "skipped": "stale"}
        sent = 0
        for member in shares.members_with_mount(share):
            with tenant.as_user(member), tenant.as_partition(share.partition()):
                sent += push.run_heads_up(body.todo_id, body.due, now, send=push.send_fcm).get("sent", 0)
        return {"sent": sent}
    with tenant.as_user(user):
        return push.run_heads_up(body.todo_id, body.due, now, send=push.send_fcm)

@router.post("/internal/sync-calendar/{todo_id}")
def sync_calendar(todo_id: str, body: SyncCalendarBody) -> dict:
    """Cloud Tasks delivery for one calendar sync (OIDC-verified in require_user)."""
    from app import calendar_jobs
    user = (body.user or auth.owner()).lower()
    if user not in auth.allowed_emails():
        raise HTTPException(400, "unknown user")
    with tenant.as_user(user):
        return calendar_jobs.run_calendar_sync(body.calendar_id or todo_id,
                                               client_session_id=body.client_session_id)
