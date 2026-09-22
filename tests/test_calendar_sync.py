import datetime as dt
from pathlib import Path

import pytest

from app import calendar_sync, models

FIXTURES = Path(__file__).parent / "fixtures" / "calendar"


def read(name):
    return (FIXTURES / name).read_text()


def test_parse_simple_events_in_window():
    events = calendar_sync.parse_ics(read("simple.ics"), dt.date(2026, 1, 1), dt.date(2026, 3, 1))
    assert {e.external_uid for e in events} == {"event-1@example.com", "event-2@example.com"}
    dentist = next(e for e in events if e.external_uid == "event-1@example.com")
    assert dentist.title == "Dentist"
    assert dentist.location == "123 Main St"
    assert dentist.due_date == dt.datetime(2026, 2, 1, 15, 0, 0)


def test_parse_clips_to_window():
    events = calendar_sync.parse_ics(read("simple.ics"), dt.date(2026, 1, 1), dt.date(2026, 2, 2))
    assert {e.external_uid for e in events} == {"event-1@example.com"}  # event-2 is Feb 3, outside


def test_parse_expands_recurrence_into_occurrences():
    events = calendar_sync.parse_ics(read("recurring.ics"), dt.date(2026, 1, 1), dt.date(2026, 4, 1))
    assert len(events) == 8
    uids = {e.external_uid for e in events}
    assert len(uids) == 8  # each occurrence gets a distinct uid
    assert all(e.title == "Team sync" for e in events)
    assert sorted(e.due_date for e in events)[0] == dt.datetime(2026, 2, 2, 10, 0, 0)


def test_parse_recurring_uid_is_stable_across_different_windows():
    # Regression: the external_uid for a given occurrence must not depend on how many
    # occurrences of that series happen to fall inside THIS call's window. Window A sees
    # two occurrences of the weekly series (Feb 2 and Feb 9); window B, sliding past Feb 2,
    # sees only the Feb 9 occurrence alone. The Feb 9 occurrence must get the same
    # external_uid in both calls, or a later sync would see it as deleted+recreated.
    window_a = calendar_sync.parse_ics(read("recurring.ics"), dt.date(2026, 2, 2), dt.date(2026, 2, 10))
    window_b = calendar_sync.parse_ics(read("recurring.ics"), dt.date(2026, 2, 9), dt.date(2026, 2, 10))
    assert len(window_a) == 2
    assert len(window_b) == 1
    feb_9 = dt.datetime(2026, 2, 9, 10, 0, 0)
    uid_in_a = next(e.external_uid for e in window_a if e.due_date == feb_9)
    uid_in_b = next(e.external_uid for e in window_b if e.due_date == feb_9)
    assert uid_in_a == uid_in_b


def test_parse_all_day_event_is_midnight():
    events = calendar_sync.parse_ics(read("allday.ics"), dt.date(2026, 1, 1), dt.date(2026, 3, 1))
    assert events[0].due_date == dt.datetime(2026, 2, 10, 0, 0, 0)


def test_parse_bad_input_raises():
    with pytest.raises(calendar_sync.CalendarSyncError):
        calendar_sync.parse_ics("not an ics file", dt.date(2026, 1, 1), dt.date(2026, 3, 1))


def _todo(uid, title, due, location=None):
    return models.Todo(title=title, type="calendar_event", external_uid=uid,
                       due_date=due, location=location)


def test_diff_creates_updates_deletes():
    kept = calendar_sync.ParsedEvent("kept@x", "Same", dt.datetime(2026, 2, 1, 9), None)
    changed = calendar_sync.ParsedEvent("changed@x", "New title", dt.datetime(2026, 2, 2, 9), None)
    new = calendar_sync.ParsedEvent("new@x", "Brand new", dt.datetime(2026, 2, 3, 9), None)
    existing = {
        "kept@x": _todo("kept@x", "Same", dt.datetime(2026, 2, 1, 9)),
        "changed@x": _todo("changed@x", "Old title", dt.datetime(2026, 2, 2, 9)),
        "gone@x": _todo("gone@x", "No longer in feed", dt.datetime(2026, 2, 5, 9)),
    }
    to_create, to_update, to_delete = calendar_sync.diff_events([kept, changed, new], existing)
    assert to_create == [new]
    assert [u for _, u in to_update] == [changed]
    assert to_delete == [str(existing["gone@x"].todo_id)]
