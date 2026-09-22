"""Push device registration and the Cloud Scheduler / Tasks / Pub/Sub callbacks."""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, HTTPException

from app import auth, db, push, tenant

log = logging.getLogger(__name__)
router = APIRouter()

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
    for email in auth.ALLOWED_EMAILS:
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
    if user not in auth.ALLOWED_EMAILS:
        raise HTTPException(400, "unknown user")
    with tenant.as_user(user):
        return push.run_heads_up(body.todo_id, body.due, datetime.datetime.now(datetime.UTC), send=push.send_fcm)
