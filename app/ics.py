"""Render the open, dated todos as an iCalendar (RFC 5545) feed for calendar apps
to subscribe to. Read-only; see docs/okf/features/calendar-feed.md."""
from __future__ import annotations

import datetime

from app import models

TIMED_MINUTES = 30
_MIDNIGHT = datetime.time(0, 0)


def escape_text(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", r"\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def fold(line: str) -> str:
    """Fold to at most 75 octets per line, never splitting a UTF-8 character."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, limit = [], 75
    while raw:
        cut = min(limit, len(raw))
        while cut < len(raw) and (raw[cut] & 0xC0) == 0x80:  # inside a multi-byte character
            cut -= 1
        parts.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
        limit = 74  # continuation lines start with a space
    return "\r\n ".join(parts)


def _event(todo: models.Todo, parent_title: str | None, stamp: str) -> list[str]:
    due = todo.due_date
    assert due is not None  # callers only pass dated todos
    lines = ["BEGIN:VEVENT", f"UID:{todo.todo_id}@now", f"DTSTAMP:{stamp}", f"SEQUENCE:{todo.version}"]
    if due.time() == _MIDNIGHT:  # all-day (see docs/okf/features/due-time.md)
        lines.append(f"DTSTART;VALUE=DATE:{due:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{due.date() + datetime.timedelta(days=1):%Y%m%d}")
    else:  # floating time: the user's wall clock, whatever timezone the calendar is in
        lines.append(f"DTSTART:{due:%Y%m%dT%H%M%S}")
        lines.append(f"DTEND:{due + datetime.timedelta(minutes=TIMED_MINUTES):%Y%m%dT%H%M%S}")
    lines.append(f"SUMMARY:{escape_text(todo.title)}")
    if parent_title:
        lines.append(f"DESCRIPTION:{escape_text('Subtask of: ' + parent_title)}")
    lines.append("TRANSP:TRANSPARENT")  # a todo must not make the calendar look busy
    lines.append("END:VEVENT")
    return lines


def build_calendar(todos_by_id: dict[str, models.Todo], now: datetime.datetime | None = None) -> str:
    """Every live, not-done todo with a due date becomes one event. A repeating
    todo is one event: its next occurrence only exists once it is completed."""
    stamp = (now or models.utc_now()).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//now//todos//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:now", "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
             "X-PUBLISHED-TTL:PT1H"]
    open_dated = sorted((t for t in todos_by_id.values() if t.due_date and not t.done and not t.deleted),
                        key=lambda t: (t.due_date, str(t.todo_id)))
    for t in open_dated:
        parent = todos_by_id.get(str(t.parent_id)) if t.parent_id else None
        lines += _event(t, parent.title if parent else None, stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
