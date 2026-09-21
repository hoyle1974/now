"""Push device registration and the Cloud Scheduler / Tasks / Pub/Sub callbacks."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, HTTPException

from app import db, push

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
    """Cloud Scheduler tick (OIDC-verified in require_user): send due reminders."""
    return push.run_notify(datetime.datetime.now(datetime.UTC), send=push.send_fcm)

@router.post("/internal/budget-alert")
def budget_alert(body: push.PubSubEnvelope) -> dict:
    """Pub/Sub push of a Cloud Billing budget notification (OIDC-verified in require_user):
    tell the owner's devices immediately (rule #1: zero GCP cost)."""
    return push.run_budget_alert(body.message.data, datetime.datetime.now(datetime.UTC), send=push.send_fcm)

@router.post("/internal/notify-todo")
def notify_todo(body: push.HeadsUp) -> dict:
    """Cloud Tasks delivery for one heads-up (OIDC-verified in require_user)."""
    return push.run_heads_up(body.todo_id, body.due, datetime.datetime.now(datetime.UTC), send=push.send_fcm)
