import datetime as dt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from app import auth, db, models, push, tenant
from app.main import app
from tests.helpers import TEST_USER, act_as, wipe_users

UTC = dt.timezone.utc
c = TestClient(app)
# 2026-09-19 16:00 UTC is 09:00 in Los Angeles.
NINE_LA = dt.datetime(2026, 9, 19, 16, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def setup():
    act_as(app)
    db.init()
    wipe_users()
    token = tenant.set_user(TEST_USER)
    yield
    tenant.reset(token)
    db.teardown()


def add_todo(title, due, done=False, deleted=False):
    t = models.Todo(title=title, due_date=dt.datetime.fromisoformat(due), done=done, deleted=deleted)
    db.create_todo(t)
    return t


class Fake:
    """Stands in for FCM: records sends, optionally raises."""
    def __init__(self, exc=None):
        self.sent, self.exc = [], exc

    def __call__(self, token, p):
        if self.exc:
            raise self.exc
        self.sent.append((token, p.title))


# ---- storage ----

def test_device_upsert_is_idempotent_and_delete_removes():
    db.upsert_push_device("d1", "tok", "America/Los_Angeles", "ios")
    db.upsert_push_device("d1", "tok", "America/New_York", "ios")
    devices = db.list_push_devices()
    assert len(devices) == 1 and devices[0]["tz"] == "America/New_York" and devices[0]["id"] == "d1"
    db.delete_push_device("d1")
    assert db.list_push_devices() == []


def test_marker_round_trip():
    assert db.get_push_marker("k") is None
    db.put_push_marker("k", ["a", "b"], NINE_LA)
    assert db.get_push_marker("k") == ["a", "b"]
    db.put_push_marker("empty", [], NINE_LA)
    assert db.get_push_marker("empty") == []


def test_due_window_query_excludes_done_deleted_and_later():
    keep = add_todo("keep", "2026-09-19T10:00:00")
    add_todo("done", "2026-09-19T10:00:00", done=True)
    add_todo("deleted", "2026-09-19T10:00:00", deleted=True)
    add_todo("later", "2026-09-30T10:00:00")
    got = db.get_due_todos(dt.datetime(2026, 9, 21))
    assert [t.todo_id for t in got] == [keep.todo_id]


# ---- routes ----

def test_register_upserts_one_device():
    body = {"token": "tok-1", "tz": "America/Los_Angeles", "platform": "ios"}
    assert c.post("/push/devices", json=body).status_code == 200
    assert c.post("/push/devices", json=body).status_code == 200
    assert len(db.list_push_devices()) == 1


def test_register_rejects_bad_tz_and_empty_token():
    assert c.post("/push/devices", json={"token": "t", "tz": "Nope/Nope"}).status_code == 400
    assert c.post("/push/devices", json={"token": "", "tz": "UTC"}).status_code == 422


def test_unregister_removes_the_device():
    c.post("/push/devices", json={"token": "tok-1", "tz": "UTC"})
    assert c.post("/push/devices/unregister", json={"token": "tok-1"}).status_code == 200
    assert db.list_push_devices() == []


def test_notify_route_returns_counts(monkeypatch):
    monkeypatch.setattr(push, "send_fcm", Fake())
    r = c.post("/internal/notify")
    assert r.status_code == 200 and r.json() == {"devices": 0, "sent": 0, "scheduled": 0}


# ---- runner ----

def register(tz="America/Los_Angeles"):
    db.upsert_push_device(push.device_id("tok"), "tok", tz, "ios")


def test_run_notify_sends_digest_once():
    register()
    add_todo("pay rent", "2026-09-19T00:00:00")
    fake = Fake()
    assert push.run_notify(NINE_LA, send=fake) == {"devices": 1, "sent": 1, "scheduled": 0}
    assert fake.sent == [("tok", "1 due today")]
    push.run_notify(NINE_LA + dt.timedelta(minutes=10), send=fake)
    assert len(fake.sent) == 1


def test_run_notify_zero_due_writes_marker_and_sends_nothing():
    register()
    fake = Fake()
    assert push.run_notify(NINE_LA, send=fake) == {"devices": 1, "sent": 0, "scheduled": 0}
    assert db.get_push_marker(f"digest:2026-09-19:{push.device_id('tok')}") == []


def test_run_notify_writes_marker_even_when_send_fails():
    register()
    add_todo("a", "2026-09-19T00:00:00")
    push.run_notify(NINE_LA, send=Fake(exc=RuntimeError("boom")))
    fake = Fake()
    push.run_notify(NINE_LA, send=fake)
    assert fake.sent == []  # fail closed: no duplicate on retry


def test_run_notify_deletes_dead_device():
    register()
    add_todo("a", "2026-09-19T00:00:00")
    push.run_notify(NINE_LA, send=Fake(exc=push.DeadToken()))
    assert db.list_push_devices() == []


def test_run_notify_sends_one_digest_to_each_device_and_no_heads_up():
    register()
    db.upsert_push_device(push.device_id("tok2"), "tok2", "America/New_York", "web")
    add_todo("dentist", "2026-09-19T15:00:00")  # timed, later today: listed in the digest, no extra heads-up
    fake = Fake()
    assert push.run_notify(dt.datetime(2026, 9, 19, 21, 30, tzinfo=UTC), send=fake) == {"devices": 2, "sent": 2, "scheduled": 0}
    assert sorted(fake.sent) == [("tok", "1 due today"), ("tok2", "1 due today")]
    push.run_notify(dt.datetime(2026, 9, 19, 22, 30, tzinfo=UTC), send=fake)
    assert len(fake.sent) == 2


# ---- scheduler auth ----

def request_for(path, token=None):
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return Request({"type": "http", "method": "POST", "path": path, "headers": headers, "query_string": b""})


@pytest.fixture
def notify_env(monkeypatch):
    monkeypatch.setenv("NOTIFY_AUDIENCE", "https://now.example")
    monkeypatch.setenv("NOTIFY_CALLER", "now-notify@proj.iam.gserviceaccount.com")

    def verify(token, audience):
        if token != "good" or audience != "https://now.example":
            raise ValueError("bad token")
        return {"email": "now-notify@proj.iam.gserviceaccount.com", "email_verified": True}
    monkeypatch.setattr(auth, "_verify_oidc", verify)


def test_notify_accepts_only_the_scheduler(notify_env, monkeypatch):
    auth.require_user(request_for("/internal/notify", "good"))  # no exception
    for bad in (None, "nope"):
        with pytest.raises(HTTPException) as e:
            auth.require_user(request_for("/internal/notify", bad))
        assert e.value.status_code == 401


def test_notify_rejects_wrong_caller(notify_env, monkeypatch):
    monkeypatch.setattr(auth, "_verify_oidc", lambda t, a: {"email": "evil@x.com", "email_verified": True})
    with pytest.raises(HTTPException) as e:
        auth.require_user(request_for("/internal/notify", "good"))
    assert e.value.status_code == 403


def test_notify_disabled_without_env(monkeypatch):
    monkeypatch.delenv("NOTIFY_AUDIENCE", raising=False)
    monkeypatch.delenv("NOTIFY_CALLER", raising=False)
    with pytest.raises(HTTPException) as e:
        auth.require_user(request_for("/internal/notify", "good"))
    assert e.value.status_code == 403


def test_a_firebase_login_does_not_open_the_notify_route(notify_env, monkeypatch):
    monkeypatch.setattr(auth, "_verify_oidc", lambda t, a: (_ for _ in ()).throw(ValueError("not a scheduler token")))
    with pytest.raises(HTTPException) as e:
        auth.require_user(request_for("/internal/notify", "a-firebase-id-token"))
    assert e.value.status_code == 401


# ---- budget alerts ----

def budget_msg(**kw):
    import base64, json
    payload = {"budgetDisplayName": "now-app monthly budget", "costAmount": 0.03, "budgetAmount": 1.0,
               "costIntervalStart": "2026-09-01T07:00:00Z", "currencyCode": "USD", **kw}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_budget_alert_pushes_any_hour_to_every_device_once():
    register()
    fake = Fake()
    now = dt.datetime(2026, 9, 21, 3, 0, tzinfo=dt.timezone.utc)  # 3 AM UTC: not 9:00
    out = push.run_budget_alert(budget_msg(alertThresholdExceeded=0.01), now, send=fake)
    assert out == {"sent": 1}
    assert fake.sent == [("tok", "GCP COST ALERT")]
    assert push.run_budget_alert(budget_msg(alertThresholdExceeded=0.01), now, send=fake)["skipped"] == "already sent"
    assert len(fake.sent) == 1
    assert push.run_budget_alert(budget_msg(alertThresholdExceeded=0.5), now, send=fake) == {"sent": 1}


def test_budget_alert_ignores_routine_updates_and_garbage():
    fake = Fake()
    now = dt.datetime(2026, 9, 21, tzinfo=dt.timezone.utc)
    assert push.run_budget_alert(budget_msg(), now, send=fake)["skipped"] == "no threshold crossed"
    assert push.run_budget_alert("!!not base64 json", now, send=fake)["skipped"] == "unreadable"
    assert fake.sent == []


def test_budget_push_text_actual_and_forecast():
    a = push.budget_push({"costAmount": 0.03, "budgetAmount": 1, "alertThresholdExceeded": 0.01, "costIntervalStart": "2026-09-01T07:00:00Z"})
    assert a.body.startswith("$0.03 spent of the $1.00 budget (1%)")
    f = push.budget_push({"costAmount": 0.5, "budgetAmount": 1, "forecastThresholdExceeded": 1.0, "costIntervalStart": "2026-09-01T07:00:00Z"})
    assert f.body.startswith("Forecast to reach 100%") and f.key != a.key


def test_budget_route_accepts_only_the_pubsub_identity(notify_env):
    auth.require_user(request_for("/internal/budget-alert", "good"))  # no exception
    for bad in (None, "nope", "a-firebase-id-token"):
        with pytest.raises(HTTPException) as e:
            auth.require_user(request_for("/internal/budget-alert", bad))
        assert e.value.status_code == 401


def test_budget_route_returns_counts(monkeypatch):
    monkeypatch.setattr(push, "send_fcm", Fake())
    register()
    r = c.post("/internal/budget-alert", json={"message": {"data": budget_msg(alertThresholdExceeded=1.0)}})
    assert r.status_code == 200 and r.json() == {"sent": 1}


def test_digest_runs_for_every_user_and_never_crosses(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ("me@example.com", "kid@example.com"))
    sent = []
    for email in ("me@example.com", "kid@example.com"):
        with tenant.as_user(email):
            db.upsert_push_device(f"dev-{email}", f"tok-{email}", "America/Los_Angeles", "ios")
            db.create_todo(models.Todo(title=f"due for {email}", due_date=dt.datetime(2026, 9, 19, 9, 0)))
    from app.routes import notifications
    monkeypatch.setattr(push, "send_fcm", lambda token, p: sent.append((token, p.body)))
    out = notifications.notify()
    assert out["devices"] == 2
    tokens = {t for t, _ in sent}
    assert tokens == {"tok-me@example.com", "tok-kid@example.com"}
    for token, body in sent:
        assert token.split("tok-")[1] in body  # each device only hears about its own owner's todo


def test_heads_up_binds_the_user_named_in_the_task(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ("me@example.com", "kid@example.com"))
    from app.routes import notifications
    seen = []
    monkeypatch.setattr(push, "run_heads_up", lambda todo_id, due, now, send=None: seen.append(tenant.current()) or {"sent": 0})
    notifications.notify_todo(push.HeadsUp(todo_id="x", due="y", user="kid@example.com"))
    notifications.notify_todo(push.HeadsUp(todo_id="x", due="y"))  # task queued before this change
    assert seen == ["kid@example.com", "me@example.com"]
    with pytest.raises(HTTPException):
        notifications.notify_todo(push.HeadsUp(todo_id="x", due="y", user="stranger@example.com"))


def test_split_schedules_a_heads_up_per_child(monkeypatch):
    calls = []
    monkeypatch.setattr("app.tasks.schedule_from_body", lambda body: calls.append(body))
    parent = add_todo("p", "2026-09-19T15:00:00")
    r = c.post(f"/todos/{parent.todo_id}/split",
               json={"descriptions": ["a", "b"], "due_date": "2026-09-19T17:30:00"})
    assert r.status_code == 200
    child_ids = [a["todo_id"] for a in r.json()["affected"][1:]]
    assert [b["todo_id"] for b in calls] == child_ids and len(child_ids) == 2
    assert all(b["due_date"].startswith("2026-09-19T17:30") for b in calls)
