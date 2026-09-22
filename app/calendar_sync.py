"""Pure ICS parsing and diffing for the calendar item type: no DB, no network
(app/tasks.py fetches; this module only turns bytes into ParsedEvents and
ParsedEvents-vs-existing-Todos into a create/update/delete plan)."""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from app import models


class CalendarSyncError(Exception):
    """The feed could not be parsed."""


@dataclass(frozen=True)
class ParsedEvent:
    external_uid: str
    title: str
    due_date: datetime.datetime  # naive; all-day events are midnight (matches due-time.md convention)
    location: str | None


def parse_ics(raw: str, window_start: datetime.date, window_end: datetime.date) -> list[ParsedEvent]:
    """Every occurrence (recurring events expanded) starting in [window_start, window_end)."""
    import icalendar
    import recurring_ical_events

    try:
        cal = icalendar.Calendar.from_ical(raw)
    except Exception as e:
        raise CalendarSyncError(f"could not parse calendar: {e}") from e

    try:
        occurrences = recurring_ical_events.of(cal).between(window_start, window_end)
    except Exception as e:
        raise CalendarSyncError(f"could not expand recurrence: {e}") from e

    # Which UIDs *can ever* produce more than one occurrence. This must be an intrinsic,
    # window-independent property of the source VEVENT (does it have an RRULE/RDATE at
    # all) — NOT how many of its occurrences happen to fall in this call's window. A
    # bounded series (e.g. RRULE COUNT=8) can have 2 occurrences in one sync's window and
    # only 1 in the next as the window slides past its end; if the suffix decision were
    # based on in-window count, that same logical occurrence would flip between a bare and
    # a suffixed external_uid across syncs, breaking diff_events' create/update matching.
    # (recurring_ical_events, as of 2.2.3, does not set RECURRENCE-ID on expanded
    # occurrences, so we can't key off that; we check the original VEVENT instead.)
    recurring_uids: set[str] = set()
    for component in cal.walk("VEVENT"):
        if component.get("RRULE") is not None or component.get("RDATE") is not None:
            uid = str(component.get("UID", ""))
            if uid:
                recurring_uids.add(uid)

    events: list[ParsedEvent] = []
    for occ in occurrences:
        start = occ["DTSTART"].dt
        all_day = not isinstance(start, datetime.datetime)
        due = (datetime.datetime.combine(start, datetime.time(0, 0)) if all_day
               else start.replace(tzinfo=None) if start.tzinfo is None
               else start.astimezone(datetime.UTC).replace(tzinfo=None))
        base_uid = str(occ.get("UID", ""))
        if not base_uid:
            continue  # an event with no UID can never be matched on the next sync; skip it
        # A recurring VEVENT's occurrences share one base UID; fold the occurrence's own
        # start time into the id so each is stable across syncs (not a loop index, which
        # would shuffle if the feed reorders events between syncs). A non-recurring
        # event's UID is already unique on its own, so it's left bare.
        uid = f"{base_uid}:{due.isoformat()}" if base_uid in recurring_uids else base_uid
        events.append(ParsedEvent(
            external_uid=uid,
            title=str(occ.get("SUMMARY", "")) or "(untitled event)",
            due_date=due,
            location=str(occ.get("LOCATION", "")).strip() or str(occ.get("DESCRIPTION", "")).strip() or None,
        ))
    return events


def diff_events(desired: list[ParsedEvent], existing: dict[str, models.Todo],
                ) -> tuple[list[ParsedEvent], list[tuple[str, ParsedEvent]], list[str]]:
    """(to_create, to_update, to_delete_ids). existing is keyed by external_uid.
    to_update pairs the existing todo's id with the new data, only when something changed."""
    desired_by_uid = {e.external_uid: e for e in desired}

    to_create = [e for uid, e in desired_by_uid.items() if uid not in existing]
    to_update = [
        (str(existing[uid].todo_id), e)
        for uid, e in desired_by_uid.items()
        if uid in existing and (
            existing[uid].title != e.title
            or existing[uid].due_date != e.due_date
            or existing[uid].location != e.location
        )
    ]
    to_delete = [str(t.todo_id) for uid, t in existing.items() if uid not in desired_by_uid]
    return to_create, to_update, to_delete


def run_calendar_sync(calendar_id: str) -> dict:
    """Stub; Task 6 fetches the feed and calls db.apply_calendar_sync."""
    return {"synced": False}
