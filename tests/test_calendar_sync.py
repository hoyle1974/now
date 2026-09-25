import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, calendar_jobs, calendar_sync, db, models, tasks, tenant
from app.main import app
from tests.helpers import TEST_USER, act_as, wipe_users

FIXTURES = Path(__file__).parent / "fixtures" / "calendar"

client = TestClient(app)


@pytest.fixture
def db_setup():
    from app.main import app as fastapi_app
    act_as(fastapi_app)
    db.init()
    wipe_users()
    token = tenant.set_user(TEST_USER)
    yield
    tenant.reset(token)
    db.teardown()


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


def test_parse_recurring_series_is_only_its_next_occurrence():
    # A weekly series is one item (its bare UID), not one per occurrence in the window.
    events = calendar_sync.parse_ics(read("recurring.ics"), dt.date(2026, 1, 1), dt.date(2026, 4, 1))
    assert len(events) == 1
    [e] = events
    assert e.external_uid == "weekly-meeting@example.com"
    assert e.due_date == dt.datetime(2026, 2, 2, 10, 0, 0)
    assert e.end_date == dt.datetime(2026, 2, 2, 10, 30, 0)
    assert e.repeat_summary == "Weekly"


def test_parse_series_moves_forward_once_an_occurrence_ends():
    # The same UID, stepped to the next occurrence: a later sync patches the item in place.
    during = calendar_sync.parse_ics(read("recurring.ics"), dt.date(2026, 2, 2), dt.date(2026, 4, 1),
                                     now=dt.datetime(2026, 2, 2, 10, 15))
    after = calendar_sync.parse_ics(read("recurring.ics"), dt.date(2026, 2, 2), dt.date(2026, 4, 1),
                                    now=dt.datetime(2026, 2, 2, 10, 30))
    assert [e.due_date for e in during] == [dt.datetime(2026, 2, 2, 10, 0)]  # still on: keep it
    assert [e.due_date for e in after] == [dt.datetime(2026, 2, 9, 10, 0)]
    assert during[0].external_uid == after[0].external_uid == "weekly-meeting@example.com"


def test_parse_series_honours_exdate_and_moved_instance():
    def next_standup(now):
        events = calendar_sync.parse_ics(read("series.ics"), now.date(), now.date() + dt.timedelta(days=60),
                                         now=now, series_window_end=now.date() + dt.timedelta(days=366))
        return next(e for e in events if e.external_uid == "standup@example.com")

    assert next_standup(dt.datetime(2026, 2, 3, 12, 0)).due_date == dt.datetime(2026, 2, 5, 11, 30)  # Wed skipped
    moved = next_standup(dt.datetime(2026, 2, 5, 10, 0))
    assert (moved.title, moved.due_date) == ("Standup (moved)", dt.datetime(2026, 2, 5, 11, 30))
    assert moved.repeat_summary == "Every weekday"
    assert next_standup(dt.datetime(2026, 2, 5, 12, 0)).due_date == dt.datetime(2026, 2, 6, 9, 30)


def test_parse_series_looks_past_the_one_off_window():
    # A yearly event months away still shows its next occurrence; one-offs keep the short window.
    now = dt.datetime(2026, 3, 1, 8, 0)
    events = calendar_sync.parse_ics(read("series.ics"), now.date(), now.date() + dt.timedelta(days=60),
                                     now=now, series_window_end=now.date() + dt.timedelta(days=366))
    birthday = next(e for e in events if e.external_uid == "birthday@example.com")
    assert birthday.due_date == dt.datetime(2026, 7, 20)
    assert birthday.repeat_summary == "Yearly"


def test_parse_all_day_series_occurrence_lasts_the_day():
    now = dt.datetime(2026, 7, 20, 18, 0)
    events = calendar_sync.parse_ics(read("series.ics"), now.date(), now.date() + dt.timedelta(days=60),
                                     now=now, series_window_end=now.date() + dt.timedelta(days=366))
    birthday = next(e for e in events if e.external_uid == "birthday@example.com")
    assert birthday.due_date == dt.datetime(2026, 7, 20)  # still today, not next year


def test_parse_event_details():
    events = {e.external_uid: e for e in calendar_sync.parse_ics(
        read("details.ics"), dt.date(2026, 2, 1), dt.date(2026, 3, 1))}
    assert "cancelled@example.com" not in events
    planning = events["planning@example.com"]
    assert planning.end_date == dt.datetime(2026, 2, 5, 15, 0)
    assert planning.location is None  # no LOCATION: the description is not used in its place
    assert planning.notes == "Agenda:\n1. Budget\n2. Q&A"  # HTML and Google's dial-in block removed
    assert planning.conference_url == "https://meet.google.com/abc-defg-hij"
    assert planning.repeat_summary is None
    assert [(a.name, a.email, a.status, a.organizer) for a in planning.attendees] == [
        ("Dana Lee", "dana@example.com", "accepted", True),
        (None, "sam@example.com", "declined", False),  # CN that only repeats the email is dropped
        (None, "kim@example.com", "tentative", False),
        ("Pat", "pat@example.com", "needs-action", False),
    ]  # rooms and resources left out
    vendor = events["zoom@example.com"]
    assert vendor.end_date == dt.datetime(2026, 2, 6, 9, 45)  # from DURATION
    assert vendor.conference_url == "https://acme.zoom.us/j/123456?pwd=xyz"
    assert vendor.attendees == ()


@pytest.mark.parametrize("rule, words", [
    ("FREQ=DAILY", "Daily"),
    ("FREQ=WEEKLY;INTERVAL=2", "Every 2 weeks"),
    ("FREQ=WEEKLY;BYDAY=MO,WE", "Weekly on Mon, Wed"),
    ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "Every weekday"),
    ("FREQ=MONTHLY;BYDAY=2TU", "Monthly on the 2nd Tue"),
    ("FREQ=MONTHLY;BYDAY=-1FR", "Monthly on the last Fri"),
    ("FREQ=YEARLY", "Yearly"),
    ("FREQ=HOURLY", "Repeats"),
])
def test_describe_rrule(rule, words):
    import icalendar
    assert calendar_sync.describe_rrule(icalendar.vRecur.from_ical(rule)) == words


def test_parse_all_day_event_is_midnight():
    events = calendar_sync.parse_ics(read("allday.ics"), dt.date(2026, 1, 1), dt.date(2026, 3, 1))
    assert events[0].due_date == dt.datetime(2026, 2, 10, 0, 0, 0)


def test_parse_bad_input_raises():
    with pytest.raises(calendar_sync.CalendarSyncError):
        calendar_sync.parse_ics("not an ics file", dt.date(2026, 1, 1), dt.date(2026, 3, 1))


def test_parse_tzaware_dtstart_converts_to_home_tz_wall_clock():
    """A tz-aware DTSTART (here TZID=America/Chicago 15:00) must become the HOME
    timezone's wall-clock time (a floating time, like everywhere else in the app —
    see due-time.md), not a UTC instant. Converting to a different home tz
    (America/Los_Angeles, 2h behind Chicago in February) must shift the wall-clock
    hour, proving this isn't just leaving it unconverted (C4)."""
    from zoneinfo import ZoneInfo
    events = calendar_sync.parse_ics(read("tzid.ics"), dt.date(2026, 1, 1), dt.date(2026, 3, 1),
                                     tz=ZoneInfo("America/Los_Angeles"))
    assert events[0].due_date == dt.datetime(2026, 2, 1, 13, 0, 0)


def test_parse_tzaware_dtstart_without_tz_arg_defaults_to_utc():
    """No `tz` given (existing callers/tests): a tz-aware DTSTART falls back to the
    previous UTC behaviour rather than erroring."""
    events = calendar_sync.parse_ics(read("tzid.ics"), dt.date(2026, 1, 1), dt.date(2026, 3, 1))
    assert events[0].due_date == dt.datetime(2026, 2, 1, 21, 0, 0)


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


def test_apply_calendar_sync_creates_updates_deletes(db_setup):
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    kept = calendar_sync.ParsedEvent("kept@x", "Same", dt.datetime(2026, 2, 1, 9), None)
    db.apply_calendar_sync(str(cal.todo_id), [kept])
    kept_id_before = db.get_calendar_event_children(str(cal.todo_id))["kept@x"].todo_id

    changed = calendar_sync.ParsedEvent("kept@x", "Renamed", dt.datetime(2026, 2, 1, 9), "Room 2")
    new = calendar_sync.ParsedEvent("new@x", "Brand new", dt.datetime(2026, 2, 3, 9), None)
    result = db.apply_calendar_sync(str(cal.todo_id), [changed, new])

    assert result == {"created": 1, "updated": 1, "deleted": 0}
    children = db.get_calendar_event_children(str(cal.todo_id))
    assert set(children) == {"kept@x", "new@x"}
    assert children["kept@x"].title == "Renamed"
    assert children["kept@x"].location == "Room 2"
    assert children["kept@x"].type == "calendar_event"
    assert children["kept@x"].parent_id == cal.todo_id
    # The critical property: a changed-but-still-present event is patched in place, not
    # deleted and recreated. remote-diff.js (web/remote-diff.js) identifies items by todo
    # id, not external_uid; a delete+create here would make every routine resync of an
    # unchanged calendar look like a spurious "N changes from another device" to the client.
    assert children["kept@x"].todo_id == kept_id_before
    assert children["kept@x"].version == 2  # bumped once by the in-place patch, not reset by a recreate


def test_apply_calendar_sync_stores_and_updates_details(db_setup):
    cal = models.Todo(title="Work", type="calendar")
    db.create_todo(cal)
    guest = models.Attendee(name="Dana", email="dana@example.com", status="accepted", organizer=True)
    event = calendar_sync.ParsedEvent(
        "series@x", "Standup", dt.datetime(2026, 2, 2, 9, 30), end_date=dt.datetime(2026, 2, 2, 9, 45),
        notes="Be brief", repeat_summary="Every weekday", conference_url="https://meet.google.com/x",
        attendees=(guest,))
    db.apply_calendar_sync(str(cal.todo_id), [event])
    stored = db.get_calendar_event_children(str(cal.todo_id))["series@x"]
    assert (stored.end_date, stored.notes, stored.repeat_summary, stored.conference_url) == (
        dt.datetime(2026, 2, 2, 9, 45), "Be brief", "Every weekday", "https://meet.google.com/x")
    assert stored.attendees == [guest]

    # The series' next occurrence (and a changed RSVP) patches the same item.
    declined = guest.model_copy(update={"status": "declined"})
    later = calendar_sync.ParsedEvent(
        "series@x", "Standup", dt.datetime(2026, 2, 3, 9, 30), end_date=dt.datetime(2026, 2, 3, 9, 45),
        notes="Be brief", repeat_summary="Every weekday", conference_url="https://meet.google.com/x",
        attendees=(declined,))
    assert db.apply_calendar_sync(str(cal.todo_id), [later]) == {"created": 0, "updated": 1, "deleted": 0}
    moved = db.get_calendar_event_children(str(cal.todo_id))["series@x"]
    assert moved.todo_id == stored.todo_id
    assert moved.due_date == dt.datetime(2026, 2, 3, 9, 30)
    assert moved.attendees[0].status == "declined"
    assert db.apply_calendar_sync(str(cal.todo_id), [later]) == {"created": 0, "updated": 0, "deleted": 0}


def test_calendar_events_are_indexed_by_date(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    later = calendar_sync.ParsedEvent("later@x", "Later", dt.datetime(2026, 3, 2, 9), None)
    sooner = calendar_sync.ParsedEvent("sooner@x", "Sooner", dt.datetime(2026, 2, 1, 15), None)
    mid = calendar_sync.ParsedEvent("mid@x", "Mid", dt.datetime(2026, 2, 1, 9), None)
    db.apply_calendar_sync(str(cal.todo_id), [later, sooner, mid])

    children = db.get_calendar_event_children(str(cal.todo_id))
    assert [children[uid].order_idx for uid in ("mid@x", "sooner@x", "later@x")] == [0, 1, 2]

    # A date change slides that event into place. The others keep their version:
    # order is not content.
    moved = calendar_sync.ParsedEvent("later@x", "Later", dt.datetime(2026, 1, 20, 9), None)
    before = {uid: children[uid].version for uid in ("mid@x", "sooner@x")}
    db.apply_calendar_sync(str(cal.todo_id), [moved, sooner, mid])
    children = db.get_calendar_event_children(str(cal.todo_id))
    assert [children[uid].order_idx for uid in ("later@x", "mid@x", "sooner@x")] == [0, 1, 2]
    assert children["mid@x"].version == before["mid@x"]
    assert children["sooner@x"].version == before["sooner@x"]


def test_sync_does_not_clear_a_user_set_priority(db_setup):
    cal = models.Todo(title="Work", type="calendar")
    db.create_todo(cal)
    event = calendar_sync.ParsedEvent("meet@x", "Planning", dt.datetime(2026, 2, 2, 9))
    db.apply_calendar_sync(str(cal.todo_id), [event])
    stored = db.get_calendar_event_children(str(cal.todo_id))["meet@x"]
    assert stored.priority == "normal"
    resp = client.patch(f"/todos/{stored.todo_id}", json={"priority": "low"},
                        headers={"If-Match": str(stored.version)})
    assert resp.status_code == 200 and resp.json()["priority"] == "low"

    moved = calendar_sync.ParsedEvent("meet@x", "Planning", dt.datetime(2026, 2, 3, 9))
    assert db.apply_calendar_sync(str(cal.todo_id), [moved])["updated"] == 1
    after = db.get_calendar_event_children(str(cal.todo_id))["meet@x"]
    assert after.todo_id == stored.todo_id
    assert after.priority == "low"
    assert after.due_date == dt.datetime(2026, 2, 3, 9)


def test_apply_calendar_sync_unchanged_event_is_not_written(db_setup):
    """A uid match with identical fields gets no write at all — not even a no-op patch —
    so its version/rev stay untouched and nothing looks changed to the client."""
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    same = calendar_sync.ParsedEvent("same@x", "Unchanged", dt.datetime(2026, 2, 1, 9), None)
    db.apply_calendar_sync(str(cal.todo_id), [same])
    before = db.get_calendar_event_children(str(cal.todo_id))["same@x"]

    result = db.apply_calendar_sync(str(cal.todo_id), [same])

    assert result == {"created": 0, "updated": 0, "deleted": 0}
    after = db.get_calendar_event_children(str(cal.todo_id))["same@x"]
    assert after.todo_id == before.todo_id
    assert after.version == before.version


def test_apply_calendar_sync_deletes_missing(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    db.apply_calendar_sync(str(cal.todo_id), [calendar_sync.ParsedEvent("gone@x", "Bye", dt.datetime(2026, 2, 1, 9), None)])
    gone_id = db.get_calendar_event_children(str(cal.todo_id))["gone@x"].todo_id
    result = db.apply_calendar_sync(str(cal.todo_id), [])
    assert result == {"created": 0, "updated": 0, "deleted": 1}
    assert db.get_calendar_event_children(str(cal.todo_id)) == {}
    assert db.get_deleted_todo(gone_id) is None  # hard-deleted: not in the trash either
    assert db.get_trash()[0] == []


def _calendar_with_events(parent=None, n=2):
    cal = models.Todo(title="Work", type="calendar", calendar_url="https://example.com/w.ics",
                      parent_id=None if parent is None else parent.todo_id)
    db.create_todo(cal)
    db.apply_calendar_sync(str(cal.todo_id), [
        calendar_sync.ParsedEvent(f"e{i}@x", f"Event {i}", dt.datetime(2026, 2, 1 + i, 9)) for i in range(n)])
    db.mark_calendar_synced(str(cal.todo_id), error=None)
    event_ids = [t.todo_id for t in db.get_calendar_event_children(str(cal.todo_id)).values()]
    return cal, event_ids


def test_deleting_calendar_trashes_it_and_hard_deletes_its_events(db_setup):
    cal, event_ids = _calendar_with_events()
    assert client.delete(f"/todos/{cal.todo_id}").status_code == 204
    trashed = db.get_deleted_todo(cal.todo_id)
    assert trashed.deleted
    assert trashed.last_synced_at is None  # so a restore syncs again on the next load
    assert all(db.get_deleted_todo(i) is None for i in event_ids)
    assert [t.todo_id for t, _, _ in db.get_trash()[0]] == [cal.todo_id]

    assert client.patch(f"/todos/{cal.todo_id}/undelete").status_code == 200
    restored = db.get_todo(cal.todo_id)
    assert restored is not None and restored.child_ids == []
    assert restored.calendar_url == "https://example.com/w.ics"


def test_deleting_a_list_hard_deletes_events_of_a_calendar_inside_it(db_setup):
    work = models.Todo(title="Job", type="list")
    db.create_todo(work)
    other = models.Todo(title="plain", parent_id=work.todo_id)
    db.create_todo(other)
    cal, event_ids = _calendar_with_events(parent=work)
    outside, outside_events = _calendar_with_events()
    assert client.delete(f"/todos/{work.todo_id}").status_code == 204
    assert all(db.get_deleted_todo(i) is None for i in event_ids)
    assert db.get_deleted_todo(cal.todo_id).last_synced_at is None
    assert db.get_deleted_todo(other.todo_id) is not None  # ordinary items still go to the trash
    assert all(db.get_todo(i) is not None for i in outside_events)  # another calendar is untouched
    assert db.get_todo(outside.todo_id).last_synced_at is not None


def test_patch_deleted_true_also_purges_events(db_setup):
    cal, event_ids = _calendar_with_events()
    resp = client.patch(f"/todos/{cal.todo_id}", json={"deleted": True}, headers={"If-Match": "1"})
    assert resp.status_code == 200, resp.text
    assert all(db.get_deleted_todo(i) is None for i in event_ids)


def test_deleting_a_plain_todo_still_soft_deletes(db_setup):
    t = models.Todo(title="plain")
    db.create_todo(t)
    assert client.delete(f"/todos/{t.todo_id}").status_code == 204
    assert db.get_deleted_todo(t.todo_id).deleted


def test_purge_stale_calendar_events(db_setup):
    live_cal, live_events = _calendar_with_events()
    flagged = db.get_todo(live_events[0])
    flagged.deleted = True  # how syncs before hard deletes removed events
    db.update_todo(flagged)
    old_cal, old_events = _calendar_with_events()
    trashed = db.get_todo(old_cal.todo_id)
    trashed.deleted = True  # trashed without a purge (before this change, or Clear completed)
    db.update_todo(trashed)

    assert db.purge_stale_calendar_events() == 3
    assert db.get_deleted_todo(live_events[0]) is None
    assert db.get_todo(live_events[1]) is not None
    assert all(db.get_deleted_todo(i) is None for i in old_events)
    assert db.get_deleted_todo(old_cal.todo_id).deleted  # the calendar itself stays in the trash
    assert db.purge_stale_calendar_events() == 0


def test_mark_calendar_synced(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    db.mark_calendar_synced(str(cal.todo_id), error="feed unreachable")
    refreshed = db.get_todo(cal.todo_id)
    assert refreshed.last_sync_error == "feed unreachable"
    assert refreshed.last_synced_at is not None

    db.mark_calendar_synced(str(cal.todo_id), error=None)
    refreshed = db.get_todo(cal.todo_id)
    assert refreshed.last_sync_error is None


def test_run_calendar_sync_success(db_setup, monkeypatch):
    # simple.ics's fixed fixture events are on 2026-02-01/03 (shared with the parse_ics
    # tests above, which pin their own explicit window); run_calendar_sync computes its
    # own window from the real clock, so pin "today" to fall inside that fixture's dates
    # rather than the (unrelated, drifting) real today.
    monkeypatch.setattr(calendar_sync.models, "utc_now", lambda: dt.datetime(2026, 1, 15))
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    result = calendar_jobs.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"))
    assert result["created"] == 2
    refreshed = db.get_todo(cal.todo_id)
    assert refreshed.last_sync_error is None
    assert refreshed.last_synced_at is not None


def test_run_calendar_sync_uses_home_timezone_date(db_setup, monkeypatch):
    # 02:00 UTC on Feb 2 is still the evening of Feb 1 in Los Angeles: Feb 1's evening event
    # must stay (the window starts on the home date, not the UTC one).
    from app import tasks as tasks_mod
    monkeypatch.setattr(calendar_sync.models, "utc_now", lambda: dt.datetime(2026, 2, 2, 2, 0))
    monkeypatch.setattr(tasks_mod, "home_tz", lambda devices: "America/Los_Angeles")
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    calendar_jobs.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"))
    assert "event-1@example.com" in db.get_calendar_event_children(str(cal.todo_id))  # Feb 1, 15:00


def test_run_calendar_sync_no_url_noops(db_setup):
    cal = models.Todo(title="Family", type="calendar")  # calendar_url never set
    db.create_todo(cal)
    result = calendar_jobs.run_calendar_sync(str(cal.todo_id), fetch=lambda url: (_ for _ in ()).throw(AssertionError("should not fetch")))
    assert result == {"synced": False, "reason": "no calendar_url"}


def test_run_calendar_sync_fetch_failure_keeps_existing_events(db_setup, monkeypatch):
    monkeypatch.setattr(calendar_sync.models, "utc_now", lambda: dt.datetime(2026, 1, 15))
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    calendar_jobs.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"))
    before = db.get_calendar_event_children(str(cal.todo_id))

    def failing_fetch(url):
        raise OSError("network down")

    result = calendar_jobs.run_calendar_sync(str(cal.todo_id), fetch=failing_fetch)
    assert result["synced"] is False
    after = db.get_calendar_event_children(str(cal.todo_id))
    assert set(after) == set(before)  # untouched
    refreshed = db.get_todo(cal.todo_id)
    assert "network down" in refreshed.last_sync_error
    assert refreshed.last_synced_at is not None  # updated even on failure, per spec


def test_sync_now_enqueues_for_calendar_type(db_setup, monkeypatch):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    calls = []
    monkeypatch.setattr(tasks, "create_calendar_sync_task",
                        lambda cid, csid=None, manual=False: calls.append((cid, manual)) or True)
    resp = client.post(f"/todos/{cal.todo_id}/sync", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 202
    assert calls == [(str(cal.todo_id), True)]  # manual: not deduped by the hourly page-load bucket


def test_sync_now_rejects_non_calendar(db_setup):
    t = models.Todo(title="a todo")
    db.create_todo(t)
    resp = client.post(f"/todos/{t.todo_id}/sync", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400


def test_get_tree_nudges_stale_calendar(db_setup, monkeypatch):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    calls = []
    monkeypatch.setattr(tasks, "create_calendar_sync_task", lambda cid, csid=None: calls.append(cid) or True)
    resp = client.get("/todos/tree", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200
    assert calls == [str(cal.todo_id)]  # last_synced_at is None -> stale


def test_internal_sync_calendar_requires_scheduler_auth(db_setup):
    # db_setup's act_as() overrides auth.require_user app-wide for TestClient convenience
    # (every other test in this module wants that); pop it here so this one call exercises
    # the real require_user -> verify_scheduler gate instead of the no-op override.
    saved = app.dependency_overrides.pop(auth.require_user, None)
    try:
        resp = client.post("/internal/sync-calendar/does-not-matter", json={"calendar_id": "x", "user": TEST_USER})
    finally:
        if saved is not None:
            app.dependency_overrides[auth.require_user] = saved
    assert resp.status_code in (401, 403)


# ---- client-session provenance (triggered_by) ----

def test_rev_reports_who_triggered_it(db_setup, monkeypatch):
    t = models.Todo(title="x")
    db.create_todo(t)  # an ordinary write: triggered_by stays None
    info = db.get_rev_info()
    assert info["triggered_by"] is None

    # simple.ics's fixed fixture events are on 2026-02-01/03; pin "today" inside that
    # window (see test_run_calendar_sync_success above) so the sync actually creates
    # events and bumps rev, rather than depending on the real, drifting today.
    monkeypatch.setattr(calendar_sync.models, "utc_now", lambda: dt.datetime(2026, 1, 15))
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    calendar_jobs.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"),
                                    client_session_id="session-abc")
    info = db.get_rev_info()
    assert info["triggered_by"] == "session-abc"

    # A later ordinary write (no triggered_by) must not leak the previous write's
    # attribution: run_atomic's tx.set(rev_ref, {...}) is a full replace, not a merge.
    # (Rev only moves inside run_atomic's transaction, same as every real route —
    # a bare db.create_todo() outside one, like the very first write above, never
    # touches rev at all.)
    def action() -> tuple[int, dict | None]:
        db.create_todo(models.Todo(title="y"))
        return 200, None
    db.run_atomic(None, action)
    info = db.get_rev_info()
    assert info["triggered_by"] is None


def test_get_rev_endpoint_exposes_triggered_by(db_setup):
    resp = client.get("/todos/rev")
    assert resp.status_code == 200
    body = resp.json()
    assert "triggered_by" in body
    assert body["triggered_by"] is None


def test_sync_now_threads_client_session_id(db_setup, monkeypatch):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    calls = []
    monkeypatch.setattr(tasks, "create_calendar_sync_task",
                        lambda cid, csid=None, manual=False: calls.append((cid, csid)) or True)
    resp = client.post(f"/todos/{cal.todo_id}/sync", json={"client_session_id": "session-xyz"},
                       headers={"Authorization": "Bearer test"})
    assert resp.status_code == 202
    assert calls == [(str(cal.todo_id), "session-xyz")]


def test_patch_saves_and_clears_calendar_url(db_setup):
    # Regression: PATCH validated calendar_url but never stored it, so every sync
    # no-op'd with "no calendar_url" in prod while all the model-level tests passed.
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    h = {"Authorization": "Bearer test"}
    resp = client.patch(f"/todos/{cal.todo_id}", json={"calendar_url": "https://example.com/f.ics"}, headers=h)
    assert resp.status_code == 200
    assert db.get_todo(cal.todo_id).calendar_url == "https://example.com/f.ics"

    client.patch(f"/todos/{cal.todo_id}", json={"title": "Family 2"}, headers=h)
    assert db.get_todo(cal.todo_id).calendar_url == "https://example.com/f.ics"  # omitted = kept

    client.patch(f"/todos/{cal.todo_id}", json={"calendar_url": None}, headers=h)
    assert db.get_todo(cal.todo_id).calendar_url is None  # explicit null clears


def test_get_tree_skips_freshly_synced_calendar(db_setup, monkeypatch):
    # Regression: last_synced_at round-trips through Firestore as a naive datetime;
    # comparing it with the aware "now" raised TypeError in the staleness check.
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    db.mark_calendar_synced(str(cal.todo_id), error=None)
    calls = []
    monkeypatch.setattr(tasks, "create_calendar_sync_task", lambda cid, csid=None: calls.append(cid) or True)
    resp = client.get("/todos/tree", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200
    assert calls == []  # fresh -> not nudged


def test_require_public_url_rejects_private_and_metadata(monkeypatch):
    monkeypatch.setattr(calendar_sync.socket, "getaddrinfo",
                        lambda host, port: [(0, 0, 0, "", ("93.184.216.34", 0))])
    calendar_sync._require_public_url("https://example.com/cal.ics")  # public name, public address
    cases = (
        ("http://127.0.0.1/x", "not a public address"),
        ("http://10.1.2.3/x", "not a public address"),
        ("http://169.254.169.254/computeMetadata/v1/", "not a public address"),
        ("http://metadata.google.internal/computeMetadata/v1/", "metadata host"),
        ("http://evil.metadata.google.internal/x", "metadata host"),
        ("file:///etc/passwd", "not an http"),
    )
    for url, reason in cases:
        with pytest.raises(calendar_sync.CalendarSyncError, match=reason):
            calendar_sync._require_public_url(url)


def test_require_public_url_rejects_a_name_that_resolves_private(monkeypatch):
    monkeypatch.setattr(calendar_sync.socket, "getaddrinfo",
                        lambda host, port: [(0, 0, 0, "", ("169.254.169.254", 0))])
    with pytest.raises(calendar_sync.CalendarSyncError, match="not a public address"):
        calendar_sync._require_public_url("https://evil.example/cal.ics")


class _Resp:
    def __init__(self, status=200, body=b"BEGIN:VCALENDAR", location=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.encoding = "utf-8"
        self._body = body

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def iter_content(self, chunk_size=65536):
        yield self._body

    def close(self):
        return None


def test_http_fetch_checks_each_redirect_and_caps_the_body(monkeypatch):
    monkeypatch.setattr(calendar_sync.socket, "getaddrinfo",
                        lambda host, port: [(0, 0, 0, "", ("93.184.216.34", 0))])

    def get(url, timeout, allow_redirects, stream):
        assert allow_redirects is False
        if url.endswith("/start"):
            return _Resp(302, location="http://169.254.169.254/computeMetadata/v1/")
        return _Resp(200, b"BEGIN:VCALENDAR")

    import requests
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(calendar_sync.CalendarSyncError, match="not a public address"):
        calendar_sync._http_fetch("https://example.com/start")


def test_http_fetch_http_error_includes_status(monkeypatch):
    monkeypatch.setattr(calendar_sync.socket, "getaddrinfo",
                        lambda host, port: [(0, 0, 0, "", ("93.184.216.34", 0))])

    def get(url, timeout, allow_redirects, stream):
        return _Resp(503, b"nope")

    import requests
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(calendar_sync.CalendarSyncError, match="HTTP 503"):
        calendar_sync._http_fetch("https://example.com/cal.ics")


def test_apply_calendar_sync_batches_above_the_write_cap(db_setup, monkeypatch):
    from app import db_firestore
    monkeypatch.setattr(db_firestore, "CALENDAR_SYNC_BATCH", 2)
    cal = models.Todo(title="Busy", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    before = db.get_rev()
    events = [
        calendar_sync.ParsedEvent(f"e{i}@x", f"Event {i:02d}", dt.datetime(2026, 3, 1, 9) + dt.timedelta(days=i))
        for i in range(5)
    ]
    assert db.apply_calendar_sync(str(cal.todo_id), events) == {"created": 5, "updated": 0, "deleted": 0}
    assert db.get_rev() == before + 3  # batches of 2, 2, and 1
    ordered = sorted(db.get_calendar_event_children(str(cal.todo_id)).values(), key=lambda t: t.order_idx)
    assert [t.title for t in ordered] == [f"Event {i:02d}" for i in range(5)]

    # Deletes are their own later batches, and a feed under the cap is one transaction.
    monkeypatch.setattr(db_firestore, "CALENDAR_SYNC_BATCH", 200)
    before = db.get_rev()
    assert db.apply_calendar_sync(str(cal.todo_id), events[:1])["deleted"] == 4
    assert db.get_rev() == before + 1
    assert len(db.get_calendar_event_children(str(cal.todo_id))) == 1


def test_apply_calendar_sync_retries_after_a_partial_batch(db_setup, monkeypatch):
    from app import db_firestore
    monkeypatch.setattr(db_firestore, "CALENDAR_SYNC_BATCH", 2)
    cal = models.Todo(title="Busy", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    old = [
        calendar_sync.ParsedEvent(f"old{i}@x", f"Old {i}", dt.datetime(2026, 3, 1, 9) + dt.timedelta(days=i))
        for i in range(3)
    ]
    db.apply_calendar_sync(str(cal.todo_id), old)
    desired = [
        calendar_sync.ParsedEvent(f"new{i}@x", f"New {i}", dt.datetime(2026, 4, 1, 9) + dt.timedelta(days=i))
        for i in range(3)
    ]
    real = db_firestore.run_atomic
    calls = {"n": 0}

    def fail_after_first(txn_id, fn, triggered_by=None):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated crash after first batch")
        return real(txn_id, fn, triggered_by)

    monkeypatch.setattr(db_firestore, "run_atomic", fail_after_first)
    with pytest.raises(RuntimeError, match="simulated crash"):
        db.apply_calendar_sync(str(cal.todo_id), desired)
    leftover = db.get_calendar_event_children(str(cal.todo_id))
    assert leftover  # first batch landed; later creates/deletes did not

    monkeypatch.setattr(db_firestore, "run_atomic", real)
    db.apply_calendar_sync(str(cal.todo_id), desired)
    assert set(db.get_calendar_event_children(str(cal.todo_id))) == {e.external_uid for e in desired}


def test_calendar_sync_module_does_not_import_db():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app" / "calendar_sync.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(alias.name for alias in node.names)
    assert "app.db" not in imported and "db" not in imported
    assert not any(isinstance(n, ast.FunctionDef) and n.name == "run_calendar_sync" for n in tree.body)


def test_purge_stale_calendar_events_clears_archived_events(db_setup):
    cal, event_ids = _calendar_with_events()
    trashed = db.get_todo(cal.todo_id)
    trashed.deleted = True
    db.update_todo(trashed)
    assert db.archive_expired(days=0) == 3  # the calendar and its two events
    archive = db.user_ref().collection("todos_archive")
    assert db.purge_stale_calendar_events() == 2
    left = [d.to_dict()["type"] for d in archive.stream()]
    assert left == ["calendar"]
