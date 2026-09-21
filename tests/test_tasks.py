import datetime as dt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import auth, db, models, push, tasks
from app.main import app

UTC = dt.timezone.utc
LA = "America/Los_Angeles"
app.dependency_overrides[auth.require_user] = lambda: None
c = TestClient(app)


def at(iso_utc):
    return dt.datetime.fromisoformat(iso_utc).replace(tzinfo=UTC)


@pytest.fixture(autouse=True)
def setup():
    db.init()
    for name in ("todos", "txn_log", "meta", "push_devices", "push_sent"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield
    db.teardown()


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, todo_id, due_iso, fire_at):
        self.calls.append((todo_id, due_iso, fire_at))
        return True


class Sender:
    def __init__(self, exc=None):
        self.sent, self.exc = [], exc

    def __call__(self, token, p):
        if self.exc:
            raise self.exc
        self.sent.append((token, p.title, p.body))


def add(title, due, done=False):
    t = models.Todo(title=title, due_date=dt.datetime.fromisoformat(due), done=done)
    db.create_todo(t)
    return t


def register(tok="tok", tz=LA):
    db.upsert_push_device(push.device_id(tok), tok, tz, "ios")


# 2026-09-19 19:00 UTC is 12:00 in Los Angeles.
NOON_LA = at("2026-09-19T19:00:00")


# ---- fire_time ----

def test_fire_time_is_one_hour_before_due_as_utc():
    fire = tasks.fire_time(dt.datetime(2026, 9, 19, 15, 0), LA, NOON_LA)  # 15:00 LA
    assert fire == at("2026-09-19T21:00:00")  # 14:00 LA


def test_fire_time_none_for_date_only_past_window_and_too_far():
    assert tasks.fire_time(dt.datetime(2026, 9, 19), LA, NOON_LA) is None                # all-day
    assert tasks.fire_time(dt.datetime(2026, 9, 19, 12, 30), LA, NOON_LA) is None        # window already open
    assert tasks.fire_time(dt.datetime(2026, 9, 21, 9, 0), LA, NOON_LA) is None          # > 24h to fire


def test_fire_time_converts_offset_aware_due():
    due = dt.datetime(2026, 9, 19, 22, 0, tzinfo=UTC)  # 15:00 LA
    assert tasks.fire_time(due, LA, NOON_LA) == at("2026-09-19T21:00:00")


def test_home_tz_is_the_most_recently_seen_device():
    old = {"tz": "Asia/Tokyo", "updated_at": at("2026-09-01T00:00:00")}
    new = {"tz": LA, "updated_at": at("2026-09-18T00:00:00")}
    assert tasks.home_tz([old, new]) == LA
    assert tasks.home_tz([{"tz": "Nope/Nope"}]) is None and tasks.home_tz([]) is None


# ---- schedule_heads_up ----

def test_schedule_creates_a_task_for_a_timed_todo():
    register()
    rec = Recorder()
    ok = tasks.schedule_heads_up("id1", dt.datetime(2026, 9, 19, 15, 0), False, False, NOON_LA, create=rec)
    assert ok and rec.calls == [("id1", "2026-09-19T15:00:00", at("2026-09-19T21:00:00"))]


@pytest.mark.parametrize("done,deleted,due", [
    (True, False, dt.datetime(2026, 9, 19, 15, 0)),
    (False, True, dt.datetime(2026, 9, 19, 15, 0)),
    (False, False, None),
    (False, False, dt.datetime(2026, 9, 19)),
    (False, False, dt.datetime(2027, 1, 1, 9, 0)),
])
def test_schedule_skips(done, deleted, due):
    register()
    rec = Recorder()
    assert tasks.schedule_heads_up("id1", due, done, deleted, NOON_LA, create=rec) is False
    assert rec.calls == []


def test_schedule_skips_without_a_device():
    rec = Recorder()
    assert tasks.schedule_heads_up("id1", dt.datetime(2026, 9, 19, 15, 0), False, False, NOON_LA, create=rec) is False
    assert rec.calls == []


def test_schedule_never_raises():
    register()

    def boom(*a):
        raise RuntimeError("tasks down")
    assert tasks.schedule_heads_up("id1", dt.datetime(2026, 9, 19, 15, 0), False, False, NOON_LA, create=boom) is False


def test_create_task_is_off_without_env(monkeypatch):
    monkeypatch.delenv("REMINDER_QUEUE", raising=False)
    assert tasks.create_task("id1", "2026-09-19T15:00:00", NOON_LA) is False


def test_task_name_is_stable_and_changes_with_the_due_time():
    a = tasks._task_name("q", "id", "2026-09-19T15:00:00")
    assert a == tasks._task_name("q", "id", "2026-09-19T15:00:00")
    assert a != tasks._task_name("q", "id", "2026-09-19T16:00:00")
    assert a.startswith("q/tasks/soon-id-")


# ---- the daily run schedules ----

def test_daily_run_schedules_tasks_for_todays_and_tomorrows_timed_todos():
    register()
    add("dentist", "2026-09-19T15:00:00")
    add("allday", "2026-09-19T00:00:00")
    rec = Recorder()
    out = push.run_notify(at("2026-09-19T16:00:00"), send=Sender(), create_task=rec)  # 09:00 LA
    assert out["scheduled"] == 1 and [c[1] for c in rec.calls] == ["2026-09-19T15:00:00"]


# ---- the write routes schedule ----

def test_write_routes_schedule_through_schedule_from_body(monkeypatch):
    seen = []
    monkeypatch.setattr(tasks, "schedule_from_body", lambda body: seen.append(body))
    r = c.post("/todos", json={"title": "x", "due_date": "2026-09-19T15:00:00"})
    assert r.status_code == 200 and seen[-1]["due_date"] == "2026-09-19T15:00:00"
    tid = r.json()["todo_id"]
    c.patch(f"/todos/{tid}", json={"due_date": "2026-09-19T16:00:00"})
    assert seen[-1]["due_date"] == "2026-09-19T16:00:00"
    n = len(seen)
    c.patch(f"/todos/{tid}", headers={"If-Match": "99"}, json={"title": "stale"})  # 409: nothing scheduled
    assert len(seen) == n


def test_scheduling_failure_never_fails_the_save(monkeypatch):
    monkeypatch.setattr(tasks, "schedule_heads_up", lambda *a, **k: 1 / 0)
    assert c.post("/todos", json={"title": "x", "due_date": "2026-09-19T15:00:00"}).status_code == 200


def test_save_makes_a_task_end_to_end(monkeypatch):
    register()
    rec = Recorder()
    monkeypatch.setattr(tasks, "create_task", rec)
    soon = (dt.datetime.now(UTC) + dt.timedelta(hours=5)).astimezone(__import__("zoneinfo").ZoneInfo(LA)).replace(tzinfo=None, microsecond=0)
    if soon.time() == dt.time(0, 0):
        soon = soon.replace(minute=5)
    r = c.post("/todos", json={"title": "call", "due_date": soon.isoformat()})
    assert r.status_code == 200 and len(rec.calls) == 1 and rec.calls[0][0] == r.json()["todo_id"]


# ---- the handler ----

def test_heads_up_sends_to_every_device_once():
    register("tok"); register("tok2", "America/New_York")
    t = add("dentist", "2026-09-19T15:00:00")
    s = Sender()
    now = at("2026-09-19T21:00:00")  # 14:00 LA / 17:00 NY: past due in NY, so only LA hears it
    out = push.run_heads_up(str(t.todo_id), "2026-09-19T15:00:00", now, send=s)
    assert out == {"sent": 1} and s.sent == [("tok", "dentist", "Due at 3:00 PM, in about an hour")]
    assert push.run_heads_up(str(t.todo_id), "2026-09-19T15:00:00", now, send=s) == {"sent": 0}  # marker


@pytest.mark.parametrize("change", ["done", "deleted", "moved", "gone"])
def test_heads_up_is_silent_when_the_todo_changed(change):
    register()
    t = add("dentist", "2026-09-19T15:00:00")
    if change == "done":
        t.done = True; db.update_todo(t)
    elif change == "deleted":
        t.deleted = True; db.update_todo(t)
    elif change == "moved":
        t.due_date = dt.datetime(2026, 9, 19, 17, 0); db.update_todo(t)
    else:
        db.get_conn().collection("todos").document(str(t.todo_id)).delete()
    s = Sender()
    out = push.run_heads_up(str(t.todo_id), "2026-09-19T15:00:00", at("2026-09-19T21:00:00"), send=s)
    assert out["sent"] == 0 and s.sent == []


def test_heads_up_bad_id_and_dead_token():
    assert push.run_heads_up("not-a-uuid", "x", NOON_LA, send=Sender())["sent"] == 0
    register()
    t = add("dentist", "2026-09-19T15:00:00")
    push.run_heads_up(str(t.todo_id), "2026-09-19T15:00:00", at("2026-09-19T21:00:00"), send=Sender(exc=push.DeadToken()))
    assert db.list_push_devices() == []


def test_notify_todo_route_and_auth_path(monkeypatch):
    register()
    t = add("dentist", "2026-09-19T15:00:00")
    monkeypatch.setattr(push, "send_fcm", lambda *a: None)
    r = c.post("/internal/notify-todo", json={"todo_id": str(t.todo_id), "due": "2026-09-19T15:00:00"})
    assert r.status_code == 200 and "sent" in r.json()
    assert "/internal/notify-todo" in auth._SCHEDULER_PATHS
