"""Heads-up reminders: one Cloud Task per timed todo, delivered LEAD before it is due.

Tasks are created when a todo with a timed due date in the next day is saved (routes in
app/main.py) and by the daily digest run (push.run_notify), so both paths end up with the
same task: its name is derived from the todo id and due time, and creating it twice is a
no-op. A task carries only the todo id and the due time it was made for; the handler
(push.run_heads_up) re-reads the todo and stays silent if it was completed, deleted or
moved since. Everything here is best-effort and never raises: a Cloud Tasks outage must not
fail a save. Off unless REMINDER_QUEUE (plus NOTIFY_AUDIENCE / NOTIFY_CALLER) is set.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import logging
import os
from collections.abc import Callable

from app import push

log = logging.getLogger(__name__)

LEAD = datetime.timedelta(hours=1)
HORIZON = datetime.timedelta(hours=24)  # tasks are made at most this far ahead of their fire time
HEADS_UP_PATH = "/internal/notify-todo"
_UTC = datetime.UTC
_client = None


def fire_time(due: datetime.datetime, tz: str, now_utc: datetime.datetime) -> datetime.datetime | None:
    """When to send the heads-up (UTC), or None: date-only todo, the hour before it already
    started, or it is more than HORIZON away (a later run or save will pick it up)."""
    zone = push._zone(tz)
    local_due = push._local_due(_Due(due), zone)
    if not push._is_timed(local_due):
        return None
    now = now_utc.astimezone(zone).replace(tzinfo=None)
    fire_local = local_due - LEAD
    if fire_local <= now or fire_local - now > HORIZON:
        return None
    return fire_local.replace(tzinfo=zone).astimezone(_UTC)


class _Due:
    """push._local_due wants an object with .due_date."""
    def __init__(self, due):
        self.due_date = due


def home_tz(devices: list[dict]) -> str | None:
    """A todo's due time is a bare wall-clock time, so one timezone must turn it into an
    instant: the most recently seen device's (travel just works, no setting needed)."""
    known = [d for d in devices if push.valid_tz(d.get("tz"))]
    if not known:
        return None
    return max(known, key=lambda d: d.get("updated_at") or datetime.datetime.min.replace(tzinfo=_UTC))["tz"]


def _task_name(queue: str, todo_id: str, due_iso: str) -> str:
    return f"{queue}/tasks/soon-{todo_id}-{hashlib.sha1(due_iso.encode()).hexdigest()[:12]}"


def create_task(todo_id: str, due_iso: str, fire_at: datetime.datetime) -> bool:
    """Create the Cloud Task. False when reminders are not set up here; an existing task is fine."""
    global _client
    queue = os.environ.get("REMINDER_QUEUE", "")
    url = os.environ.get("NOTIFY_AUDIENCE", "").rstrip("/")
    caller = os.environ.get("NOTIFY_CALLER", "")
    if not (queue and url and caller):
        return False
    from google.api_core import exceptions
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2
    if _client is None:
        _client = tasks_v2.CloudTasksClient()
    when = timestamp_pb2.Timestamp()
    when.FromDatetime(fire_at)
    task = tasks_v2.Task(
        name=_task_name(queue, todo_id, due_iso),
        schedule_time=when,
        http_request=tasks_v2.HttpRequest(
            url=url + HEADS_UP_PATH, http_method=tasks_v2.HttpMethod.POST,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"todo_id": todo_id, "due": due_iso}).encode(),
            oidc_token=tasks_v2.OidcToken(service_account_email=caller, audience=url)))
    with contextlib.suppress(exceptions.AlreadyExists):
        _client.create_task(request={"parent": queue, "task": task}, timeout=5)
    return True


def schedule_heads_up(todo_id: str, due: datetime.datetime | None, done: bool, deleted: bool,
                      now_utc: datetime.datetime | None = None, tz: str | None = None,
                      create: Callable[[str, str, datetime.datetime], bool] | None = None) -> bool:
    """Make the heads-up task for one todo if it needs one. True when a task now exists."""
    if done or deleted or due is None:
        return False
    now_utc = now_utc or datetime.datetime.now(_UTC)
    # Cheap filter before any read: no timezone puts a todo outside this range within a day.
    naive_now = now_utc.replace(tzinfo=None)
    naive_due = due.astimezone(_UTC).replace(tzinfo=None) if due.tzinfo else due
    if not naive_now - datetime.timedelta(days=2) < naive_due < naive_now + datetime.timedelta(days=3):
        return False
    try:
        from app import db
        tz = tz or home_tz(db.list_push_devices())
        if tz is None:
            return False
        fire = fire_time(due, tz, now_utc)
        if fire is None:
            return False
        return (create or create_task)(todo_id, due.isoformat(), fire)
    except Exception:
        log.exception("heads-up task not created for %s", todo_id)
        return False


def schedule_from_body(body: dict | None) -> None:
    """For the write routes: the response body of a saved todo (JSON dict)."""
    try:
        if not body or not body.get("due_date"):
            return
        schedule_heads_up(str(body["todo_id"]), datetime.datetime.fromisoformat(body["due_date"]),
                          bool(body.get("done")), bool(body.get("deleted")))
    except Exception:
        log.exception("heads-up scheduling skipped")
