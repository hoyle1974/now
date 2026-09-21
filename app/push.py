"""Push reminders: decide what to send (pure) and send it (thin)."""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app import models

MAX_TITLES = 3
MARKER_TTL = datetime.timedelta(days=3)


class DeviceRegistration(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    tz: str = "UTC"
    platform: str = Field("", max_length=64)


class HeadsUp(BaseModel):
    """Body of a Cloud Tasks delivery (app/tasks.py): the todo and the due time the task was made for."""
    todo_id: str = Field(min_length=1, max_length=64)
    due: str = Field(min_length=1, max_length=64)


class TokenOnly(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


@dataclass(frozen=True)
class Push:
    key: str
    title: str
    body: str
    todo_ids: tuple[str, ...] = ()
    silent: bool = False  # marker only, nothing is sent


class DeadToken(Exception):
    """FCM says this device token will never work again."""


def device_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def valid_tz(name: object) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(str(name))
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name) if valid_tz(name) else ZoneInfo("UTC")


class _HasDue(Protocol):
    due_date: datetime.datetime | None


def _local_due(todo: _HasDue, zone: ZoneInfo) -> datetime.datetime:
    due = todo.due_date
    assert due is not None  # callers only pass timed todos
    return due.astimezone(zone).replace(tzinfo=None) if due.tzinfo else due


def _is_timed(due: datetime.datetime) -> bool:
    return due.time() != datetime.time(0, 0)


def plan_device(dev_id: str, tz: str, now_utc: datetime.datetime,
                todos: list[models.Todo], sent: Callable[[str], list[str] | None]) -> list[Push]:
    """What to send this device right now: at most one digest per device-local day
    (due today or overdue). The Scheduler decides *when* the tick runs; the device's
    timezone only decides which day "today" is. `sent(key)` returns the todo ids stored
    with an existing marker, or None when there is none."""
    zone = _zone(tz)
    today = now_utc.astimezone(zone).date()
    dkey = f"digest:{today.isoformat()}:{dev_id}"
    if sent(dkey) is not None:
        return []
    due = sorted(((d, t) for t in todos if not t.done and not t.deleted and t.due_date
                  for d in [_local_due(t, zone)] if d.date() <= today), key=lambda p: p[0])
    titles = ", ".join(t.title for _, t in due[:MAX_TITLES])
    if len(due) > MAX_TITLES:
        titles += f" +{len(due) - MAX_TITLES} more"
    return [Push(dkey, f"{len(due)} due today", titles, tuple(str(t.todo_id) for _, t in due), silent=not due)]


def send_fcm(token: str, p: Push) -> None:
    """One data-only web push. The service worker always shows it (iOS revokes
    permission from a page that receives pushes it does not display)."""
    import firebase_admin
    from firebase_admin import messaging
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    message = messaging.Message(
        token=token,
        data={"title": p.title, "body": p.body, "url": "/"},
        webpush=messaging.WebpushConfig(headers={"Urgency": "high", "TTL": "3600"}))
    try:
        messaging.send(message)
    except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as e:
        raise DeadToken() from e


def run_notify(now_utc: datetime.datetime, send: Callable[[str, Push], None] | None = None,
               create_task: Callable | None = None) -> dict:
    """The daily tick. Sends each device its digest, then makes a heads-up task for every
    timed todo due soon (app/tasks.py; the write routes make them too, this is the safety
    net). Reads only todos due within two days (or overdue), and nothing at all when no
    device is registered. The marker is written before the send, so a failure loses one
    push rather than repeating it."""
    from app import db, tasks
    send = send or send_fcm
    devices = db.list_push_devices()
    if not devices:
        return {"devices": 0, "sent": 0, "scheduled": 0}
    # Two days ahead covers "end of today" in any timezone; each device filters precisely.
    todos = db.get_due_todos((now_utc + datetime.timedelta(days=2)).replace(tzinfo=None))
    sent = 0
    for dev in devices:
        for p in plan_device(dev["id"], dev.get("tz", "UTC"), now_utc, todos, db.get_push_marker):
            db.put_push_marker(p.key, list(p.todo_ids), now_utc + MARKER_TTL)
            if p.silent:
                continue
            try:
                send(dev["token"], p)
                sent += 1
            except DeadToken:
                db.delete_push_device(dev["id"])
                break
            except Exception:
                logging.exception("push send failed for device %s", dev["id"])
    tz = tasks.home_tz(devices)
    scheduled = sum(tasks.schedule_heads_up(str(t.todo_id), t.due_date, t.done, t.deleted, now_utc, tz, create_task)
                    for t in todos) if tz else 0
    return {"devices": len(devices), "sent": sent, "scheduled": scheduled}


def run_heads_up(todo_id: str, due_iso: str, now_utc: datetime.datetime,
                 send: Callable[[str, Push], None] | None = None) -> dict:
    """A Cloud Task fired: tell every device the todo is due in about an hour, unless it
    was completed, deleted or moved since the task was made (then stay silent, so the
    task is done and not retried)."""
    from app import db
    send = send or send_fcm
    try:
        tid = models.TodoId(uuid.UUID(todo_id))
    except ValueError:
        return {"sent": 0, "skipped": "bad id"}
    todo = db.get_todo(tid)
    if todo is None or todo.done or todo.due_date is None or todo.due_date.isoformat() != due_iso:
        return {"sent": 0, "skipped": "stale"}
    sent = 0
    for dev in db.list_push_devices():
        zone = _zone(dev.get("tz", "UTC"))
        due = _local_due(todo, zone)
        if not _is_timed(due) or due <= now_utc.astimezone(zone).replace(tzinfo=None):
            continue
        key = f"soon:{todo.todo_id}:{due_iso}:{dev['id']}"
        if db.get_push_marker(key) is not None:
            continue
        db.put_push_marker(key, [str(todo.todo_id)], now_utc + MARKER_TTL)
        try:
            send(dev["token"], Push(key, todo.title, f"Due at {due.strftime('%-I:%M %p')}, in about an hour"))
            sent += 1
        except DeadToken:
            db.delete_push_device(dev["id"])
        except Exception:
            logging.exception("heads-up send failed for device %s", dev["id"])
    return {"sent": sent}


BUDGET_MARKER_TTL = datetime.timedelta(days=35)


class PubSubMessage(BaseModel):
    data: str = ""


class PubSubEnvelope(BaseModel):
    """What a Pub/Sub push subscription POSTs; only the message payload matters."""
    message: PubSubMessage = PubSubMessage()


def budget_push(payload: dict) -> Push | None:
    """The push for one Cloud Billing budget notification, or None when it crossed no
    threshold (budgets also publish routine spend updates every so often).
    Rule #1 of this project is zero GCP cost, so any crossing is worth a push."""
    forecast = payload.get("forecastThresholdExceeded")
    actual = payload.get("alertThresholdExceeded")
    fraction = forecast if actual is None else actual
    if fraction is None:
        return None
    try:
        cost, budget, fraction = float(payload["costAmount"]), float(payload["budgetAmount"]), float(fraction)
    except (KeyError, TypeError, ValueError):
        return None
    cur = "$" if payload.get("currencyCode", "USD") == "USD" else payload.get("currencyCode", "") + " "
    kind = "forecast" if actual is None else "actual"
    month = str(payload.get("costIntervalStart", ""))[:7]
    if kind == "forecast":
        body = (f"Forecast to reach {fraction:.0%} of the {cur}{budget:.2f} budget this month "
                f"(spent {cur}{cost:.2f} so far). Run scripts/cost-check.sh.")
    else:
        body = (f"{cur}{cost:.2f} spent of the {cur}{budget:.2f} budget ({fraction:.0%}) this month. "
                "Run scripts/cost-check.sh.")
    return Push(f"budget:{month}:{kind}:{fraction:g}", "GCP COST ALERT", body)


def run_budget_alert(data: str, now_utc: datetime.datetime,
                     send: Callable[[str, Push], None] | None = None) -> dict:
    """A Pub/Sub delivery of a budget notification: push it to every device, at any hour
    (not a reminder, so no 9:00 rule), once per month per threshold. Always answers ok
    so Pub/Sub does not redeliver garbage."""
    from app import db
    send = send or send_fcm
    try:
        p = budget_push(json.loads(base64.b64decode(data or "")))
    except Exception:
        return {"sent": 0, "skipped": "unreadable"}
    if p is None:
        return {"sent": 0, "skipped": "no threshold crossed"}
    if db.get_push_marker(p.key) is not None:
        return {"sent": 0, "skipped": "already sent"}
    db.put_push_marker(p.key, [], now_utc + BUDGET_MARKER_TTL)
    sent = 0
    for dev in db.list_push_devices():
        try:
            send(dev["token"], p)
            sent += 1
        except DeadToken:
            db.delete_push_device(dev["id"])
        except Exception:
            logging.exception("budget alert send failed for device %s", dev["id"])
    return {"sent": sent}
