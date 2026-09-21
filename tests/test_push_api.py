import datetime as dt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from app import auth, db, models, push
from app.main import app

UTC = dt.timezone.utc
app.dependency_overrides[auth.require_user] = lambda: None
c = TestClient(app)
# 2026-09-19 16:00 UTC is 09:00 in Los Angeles.
NINE_LA = dt.datetime(2026, 9, 19, 16, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def setup():
    db.init()
    for name in ("todos", "txn_log", "meta", "push_devices", "push_sent"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield
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
    assert r.status_code == 200 and r.json() == {"devices": 0, "sent": 0}


# ---- runner ----

def register(tz="America/Los_Angeles"):
    db.upsert_push_device(push.device_id("tok"), "tok", tz, "ios")


def test_run_notify_sends_digest_once():
    register()
    add_todo("pay rent", "2026-09-19T00:00:00")
    fake = Fake()
    assert push.run_notify(NINE_LA, send=fake) == {"devices": 1, "sent": 1}
    assert fake.sent == [("tok", "1 due today")]
    push.run_notify(NINE_LA + dt.timedelta(minutes=10), send=fake)
    assert len(fake.sent) == 1


def test_run_notify_zero_due_writes_marker_and_sends_nothing():
    register()
    fake = Fake()
    assert push.run_notify(NINE_LA, send=fake) == {"devices": 1, "sent": 0}
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
    assert push.run_notify(dt.datetime(2026, 9, 19, 21, 30, tzinfo=UTC), send=fake) == {"devices": 2, "sent": 2}
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
