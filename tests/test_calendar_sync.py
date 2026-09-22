import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, calendar_sync, db, models, tasks, tenant
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
    result = db.apply_calendar_sync(str(cal.todo_id), [])
    assert result == {"created": 0, "updated": 0, "deleted": 1}
    assert db.get_calendar_event_children(str(cal.todo_id)) == {}


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
    result = calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"))
    assert result["created"] == 2
    refreshed = db.get_todo(cal.todo_id)
    assert refreshed.last_sync_error is None
    assert refreshed.last_synced_at is not None


def test_run_calendar_sync_no_url_noops(db_setup):
    cal = models.Todo(title="Family", type="calendar")  # calendar_url never set
    db.create_todo(cal)
    result = calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=lambda url: (_ for _ in ()).throw(AssertionError("should not fetch")))
    assert result == {"synced": False, "reason": "no calendar_url"}


def test_run_calendar_sync_fetch_failure_keeps_existing_events(db_setup, monkeypatch):
    monkeypatch.setattr(calendar_sync.models, "utc_now", lambda: dt.datetime(2026, 1, 15))
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"))
    before = db.get_calendar_event_children(str(cal.todo_id))

    def failing_fetch(url):
        raise OSError("network down")

    result = calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=failing_fetch)
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
    monkeypatch.setattr(tasks, "create_calendar_sync_task", lambda cid, csid=None: calls.append(cid) or True)
    resp = client.post(f"/todos/{cal.todo_id}/sync", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 202
    assert calls == [str(cal.todo_id)]


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
    calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"),
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
    monkeypatch.setattr(tasks, "create_calendar_sync_task", lambda cid, csid=None: calls.append((cid, csid)) or True)
    resp = client.post(f"/todos/{cal.todo_id}/sync", json={"client_session_id": "session-xyz"},
                       headers={"Authorization": "Bearer test"})
    assert resp.status_code == 202
    assert calls == [(str(cal.todo_id), "session-xyz")]
