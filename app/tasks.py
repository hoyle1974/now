"""Heads-up reminders: one Cloud Task per timed todo, delivered LEAD before it is due.

Tasks are created when a todo with a timed due date in the next day is saved (routes in
app/routes/todos.py) and by the daily digest run (push.run_notify), so both paths end up with the
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

from app import push, tenant, types

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
            body=json.dumps({"todo_id": todo_id, "due": due_iso, "user": tenant.current(),
                             "partition": tenant.partition()}).encode(),
            oidc_token=tasks_v2.OidcToken(service_account_email=caller, audience=url)))
    with contextlib.suppress(exceptions.AlreadyExists):
        _client.create_task(request={"parent": queue, "task": task}, timeout=5)
    return True


def schedule_heads_up(todo_id: str, due: datetime.datetime | None, done: bool, deleted: bool,
                      now_utc: datetime.datetime | None = None, tz: str | None = None,
                      create: Callable[[str, str, datetime.datetime], bool] | None = None,
                      item_type: str = "todo") -> bool:
    """Make the heads-up task for one todo if it needs one. True when a task now exists."""
    if done or deleted or due is None or not types.can_type(item_type, "notifies"):
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
                          bool(body.get("done")), bool(body.get("deleted")),
                          item_type=body.get("type", "todo"))
    except Exception:
        log.exception("heads-up scheduling skipped")


CALENDAR_STALE_AFTER = datetime.timedelta(hours=6)
SYNC_CALENDAR_PATH = "/internal/sync-calendar"


def _sync_task_name(queue: str, calendar_id: str, now_utc: datetime.datetime, manual: bool = False) -> str:
    # Bucketed by hour so two page loads in the same hour dedupe to one task
    # (Cloud Tasks refuses a duplicate name; AlreadyExists is swallowed below).
    # A manual "Sync now" gets its own per-minute bucket, so it isn't swallowed
    # by a page-load task from earlier in the same hour.
    if manual:
        return f"{queue}/tasks/calsync-{calendar_id}-{now_utc.strftime('%Y%m%dT%H%M')}-manual"
    return f"{queue}/tasks/calsync-{calendar_id}-{now_utc.strftime('%Y%m%dT%H')}"


def create_calendar_sync_task(calendar_id: str, client_session_id: str | None = None,
                              now_utc: datetime.datetime | None = None, manual: bool = False) -> bool:
    """Enqueue the sync Cloud Task for one calendar, to run right away.
    Reuses the reminder queue/OIDC plumbing (no new env vars). False when
    reminders aren't configured here; an existing task for this hour is fine."""
    global _client
    queue = os.environ.get("REMINDER_QUEUE", "")
    url = os.environ.get("NOTIFY_AUDIENCE", "").rstrip("/")
    caller = os.environ.get("NOTIFY_CALLER", "")
    if not (queue and url and caller):
        return False
    now_utc = now_utc or datetime.datetime.now(_UTC)
    from google.api_core import exceptions
    from google.cloud import tasks_v2
    if _client is None:
        _client = tasks_v2.CloudTasksClient()
    task = tasks_v2.Task(
        name=_sync_task_name(queue, calendar_id, now_utc, manual),
        http_request=tasks_v2.HttpRequest(
            url=url + SYNC_CALENDAR_PATH + f"/{calendar_id}", http_method=tasks_v2.HttpMethod.POST,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"calendar_id": calendar_id, "user": tenant.current(),
                             "client_session_id": client_session_id}).encode(),
            oidc_token=tasks_v2.OidcToken(service_account_email=caller, audience=url)))
    with contextlib.suppress(exceptions.AlreadyExists):
        _client.create_task(request={"parent": queue, "task": task}, timeout=5)
    return True


def calendar_stale(last_synced_at: datetime.datetime | None, now_utc: datetime.datetime,
                   threshold: datetime.timedelta = CALENDAR_STALE_AFTER) -> bool:
    """Due for a sync: never synced, or last synced `threshold` or more ago."""
    if last_synced_at is not None and last_synced_at.tzinfo is None:
        # Firestore round-trips it without tzinfo (mark_calendar_synced stores naive UTC).
        last_synced_at = last_synced_at.replace(tzinfo=_UTC)
    return last_synced_at is None or now_utc - last_synced_at >= threshold


def enqueue_calendar_sync(calendar_id: str, last_synced_at: datetime.datetime | None,
                          now_utc: datetime.datetime, threshold: datetime.timedelta = CALENDAR_STALE_AFTER,
                          client_session_id: str | None = None, manual: bool = False,
                          create: Callable[[str, str | None], bool] | None = None) -> bool:
    """The one staleness check every trigger (list load, manual button, digest) shares.
    True when a sync was enqueued (or would have been, for the manual button which
    always calls this with last_synced_at forced stale). Never raises: the digest
    and the tree-load nudge call it and must not fail because of a calendar."""
    try:
        if not calendar_stale(last_synced_at, now_utc, threshold):
            return False
        if create:
            return create(calendar_id, client_session_id)
        if manual:
            return create_calendar_sync_task(calendar_id, client_session_id, manual=True)
        return create_calendar_sync_task(calendar_id, client_session_id)
    except Exception:
        log.exception("calendar sync not enqueued for %s", calendar_id)
        return False
