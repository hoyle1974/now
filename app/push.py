"""Push reminders: decide what to send (pure) and send it (thin)."""
from __future__ import annotations
import datetime
import hashlib
import logging
from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Field
from app import models

DIGEST_HOUR = 9
LEAD = datetime.timedelta(hours=1)
MAX_TITLES = 3
MARKER_TTL = datetime.timedelta(days=3)


class DeviceRegistration(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    tz: str = "UTC"
    platform: str = Field("", max_length=64)


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


def _local_due(todo: models.Todo, zone: ZoneInfo) -> datetime.datetime:
    due = todo.due_date
    return due.astimezone(zone).replace(tzinfo=None) if due.tzinfo else due


def _is_timed(due: datetime.datetime) -> bool:
    return due.time() != datetime.time(0, 0)


def plan_device(dev_id: str, tz: str, now_utc: datetime.datetime,
                todos: list[models.Todo], sent: Callable[[str], list[str] | None]) -> list[Push]:
    """What to send this device right now. `sent(key)` returns the todo ids stored
    with an existing marker, or None when there is none."""
    zone = _zone(tz)
    now = now_utc.astimezone(zone).replace(tzinfo=None)
    if now.hour < DIGEST_HOUR:
        return []
    today = now.date()
    nine = datetime.datetime.combine(today, datetime.time(DIGEST_HOUR))
    open_ = [(t, _local_due(t, zone)) for t in todos if not t.done and not t.deleted and t.due_date]
    out: list[Push] = []

    dkey = f"digest:{today.isoformat()}:{dev_id}"
    prior = sent(dkey)
    digest_ids = set(prior or [])
    if prior is None:
        due = sorted(((d, t) for t, d in open_ if d.date() <= today), key=lambda p: p[0])
        ids = tuple(str(t.todo_id) for _, t in due)
        titles = ", ".join(t.title for _, t in due[:MAX_TITLES])
        if len(due) > MAX_TITLES:
            titles += f" +{len(due) - MAX_TITLES} more"
        out.append(Push(dkey, f"{len(due)} due today", titles, ids, silent=not due))
        digest_ids = set(ids)

    for t, d in open_:
        if not _is_timed(d) or not datetime.timedelta(0) < d - now <= LEAD:
            continue
        key = f"soon:{t.todo_id}:{t.due_date.isoformat()}:{dev_id}"
        if sent(key) is not None:
            continue
        if d - LEAD < nine and str(t.todo_id) in digest_ids:
            continue  # its window opened overnight: the digest already covers it
        out.append(Push(key, t.title, f"Due at {d.strftime('%-I:%M %p')}, in about an hour"))
    return out


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


def run_notify(now_utc: datetime.datetime, send: Callable[[str, Push], None] | None = None) -> dict:
    """One scheduler tick. Reads only todos due within two days (or overdue), and
    nothing at all when no device is registered. The marker is written before the
    send, so a failure loses one push rather than repeating it."""
    from app import db
    send = send or send_fcm
    devices = db.list_push_devices()
    if not devices:
        return {"devices": 0, "sent": 0}
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
    return {"devices": len(devices), "sent": sent}
