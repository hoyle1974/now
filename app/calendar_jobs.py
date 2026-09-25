"""Orchestrate one calendar item sync: fetch, parse, write.

Kept out of calendar_sync.py so that module stays parse/diff/fetch-only and
does not import the db layer (which imports calendar_sync for diff_events).
"""
from __future__ import annotations

import datetime
import uuid

from app import calendar_sync, db, models, push, tasks


def run_calendar_sync(calendar_id: str, fetch=None, client_session_id: str | None = None) -> dict:
    """Fetch, parse, diff and write. Never raises: failure is recorded on the
    calendar item (last_sync_error) rather than propagated, so a Cloud Task
    delivery always acks and is never retried into a storm."""
    fetch = fetch or calendar_sync._http_fetch
    cal = db.get_todo(models.TodoId(uuid.UUID(calendar_id)))
    if cal is None:
        return {"synced": False, "reason": "calendar not found"}
    if not cal.calendar_url:
        return {"synced": False, "reason": "no calendar_url"}

    zone = push._zone(tasks.home_tz(db.list_push_devices()) or "UTC")
    # "Now" and "today" on the home wall clock, like every due_date; the UTC date would
    # start the window a day early each evening west of Greenwich.
    now = models.utc_now().replace(tzinfo=datetime.UTC).astimezone(zone).replace(tzinfo=None)
    today = now.date()
    try:
        raw = fetch(cal.calendar_url)
        events = calendar_sync.parse_ics(
            raw, today, today + datetime.timedelta(days=calendar_sync.WINDOW_DAYS), zone, now=now,
            series_window_end=today + datetime.timedelta(days=calendar_sync.SERIES_WINDOW_DAYS))
    except Exception as e:
        db.mark_calendar_synced(calendar_id, error=str(e))
        return {"synced": False, "error": str(e)}

    result = db.apply_calendar_sync(calendar_id, events, triggered_by=client_session_id)
    db.mark_calendar_synced(calendar_id, error=None)
    return {"synced": True, **result}
