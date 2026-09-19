"""Next due date for a repeating todo. Pure functions, so the date math is easy to test."""
from __future__ import annotations

import calendar
import datetime

from app import models

_MAX_STEPS = 100_000  # a safety net against a pathological rule, not a real limit


def _add_months(base: datetime.datetime, months: int) -> datetime.datetime:
    """base plus whole months, clamped to the month's last day (Jan 31 + 1 -> Feb 28)."""
    index = base.year * 12 + (base.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return base.replace(year=year, month=month, day=day)


def next_due(due: datetime.datetime | None, repeat: models.Repeat,
             today: datetime.date) -> datetime.datetime:
    """The first occurrence strictly after `today`, stepping from the due date.

    Stepping from the due date (not from today) keeps the schedule: a weekly
    Monday todo finished on Thursday comes back next Monday. Month and year
    steps are always measured from the original due date so a clamped Feb 28
    does not drag later months off the 31st. A due time of day is kept. With no
    due date the schedule starts from today.
    """
    base = due if due is not None else datetime.datetime.combine(today, datetime.time())

    if repeat.unit == "weekday":
        candidate = base
        for _ in range(_MAX_STEPS):
            candidate += datetime.timedelta(days=1)
            if candidate.weekday() < 5 and candidate.date() > today:
                return candidate
        raise ValueError("repeat rule did not converge")

    for k in range(1, _MAX_STEPS):
        n = repeat.every * k
        if repeat.unit == "day":
            candidate = base + datetime.timedelta(days=n)
        elif repeat.unit == "week":
            candidate = base + datetime.timedelta(weeks=n)
        elif repeat.unit == "month":
            candidate = _add_months(base, n)
        else:  # year
            candidate = _add_months(base, 12 * n)
        if candidate.date() > today:
            return candidate
    raise ValueError("repeat rule did not converge")
