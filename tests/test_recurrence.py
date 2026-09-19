"""Next-due-date math for repeating todos (app/recurrence.py)."""
import datetime

from app.models import Repeat
from app.recurrence import next_due

D = datetime.date
DT = datetime.datetime


def nxt(due, unit, every, today):
    return next_due(due, Repeat(unit=unit, every=every), today)


# 2026-09-14 is a Monday.

def test_daily_moves_one_day_past_today_when_completed_on_the_due_day():
    assert nxt(DT(2026, 9, 14), "day", 1, D(2026, 9, 14)) == DT(2026, 9, 15)


def test_every_n_days_steps_by_n():
    assert nxt(DT(2026, 9, 14), "day", 3, D(2026, 9, 14)) == DT(2026, 9, 17)


def test_late_completion_skips_to_the_next_occurrence_after_today():
    assert nxt(DT(2026, 9, 14), "day", 1, D(2026, 9, 18)) == DT(2026, 9, 19)
    assert nxt(DT(2026, 9, 14), "week", 1, D(2026, 9, 17)) == DT(2026, 9, 21)


def test_early_completion_still_goes_one_step_from_the_due_date():
    assert nxt(DT(2026, 9, 18), "week", 1, D(2026, 9, 15)) == DT(2026, 9, 25)


def test_every_two_weeks():
    assert nxt(DT(2026, 9, 14), "week", 2, D(2026, 9, 14)) == DT(2026, 9, 28)


def test_weekday_skips_the_weekend():
    assert nxt(DT(2026, 9, 18), "weekday", 1, D(2026, 9, 18)) == DT(2026, 9, 21)  # Fri -> Mon
    assert nxt(DT(2026, 9, 14), "weekday", 1, D(2026, 9, 14)) == DT(2026, 9, 15)  # Mon -> Tue
    assert nxt(DT(2026, 9, 18), "weekday", 1, D(2026, 9, 20)) == DT(2026, 9, 21)  # done on Sunday


def test_month_clamps_to_month_end_without_drifting():
    assert nxt(DT(2026, 1, 31), "month", 1, D(2026, 1, 31)) == DT(2026, 2, 28)
    # Completed late in March: still anchored on the 31st, not the 28th.
    assert nxt(DT(2026, 1, 31), "month", 1, D(2026, 3, 1)) == DT(2026, 3, 31)


def test_year_clamps_leap_day():
    assert nxt(DT(2028, 2, 29), "year", 1, D(2028, 2, 29)) == DT(2029, 2, 28)


def test_time_of_day_is_kept():
    assert nxt(DT(2026, 9, 14, 15, 30), "day", 1, D(2026, 9, 14)) == DT(2026, 9, 15, 15, 30)


def test_no_due_date_counts_from_today():
    assert nxt(None, "day", 1, D(2026, 9, 19)) == DT(2026, 9, 20)
    assert nxt(None, "week", 2, D(2026, 9, 19)) == DT(2026, 10, 3)
