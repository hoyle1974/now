"""Reminders for shared items: every member with the share in their list hears about it."""
import datetime as dt

import pytest

from app import db, models, push, tenant
from app.routes import notifications
from tests.helpers import OTHER_USER, TEST_USER, wipe_users
from tests.share_fixtures import CHILD, ROOT, add_mount, make_share

UTC = dt.timezone.utc
NINE_LA = dt.datetime(2026, 9, 19, 16, 0, tzinfo=UTC)  # 09:00 in Los Angeles
SHARE = f"shares/{ROOT}"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("SHARING_ENABLED", "1")
    db.init()
    wipe_users()
    yield
    db.teardown()


def due_child(when="2026-09-19T15:00:00"):
    with tenant.as_user(TEST_USER), tenant.as_partition(SHARE):
        todo = db.get_todo(models.TodoId(CHILD))
        todo.due_date = dt.datetime.fromisoformat(when)
        db.run_atomic(None, lambda: (db.update_todo(todo), (200, None))[-1])


def device(email):
    with tenant.as_user(email):
        db.upsert_push_device(f"dev-{email}", f"tok-{email}", "America/Los_Angeles", "ios")


class Sender:
    def __init__(self):
        self.sent = []

    def __call__(self, token, p):
        self.sent.append((token, p.title, p.body))


def test_digest_includes_shared_due_items():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER, OTHER_USER))
    due_child()
    device(OTHER_USER)
    send = Sender()
    with tenant.as_user(OTHER_USER):
        out = push.run_notify(NINE_LA, send=send, create_task=lambda *a: True)
    assert out["sent"] == 1
    assert send.sent == [(f"tok-{OTHER_USER}", "1 due today", "Book hotel")]


def test_removed_mount_gets_no_shared_digest():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER,))
    add_mount(OTHER_USER, deleted=True)
    due_child()
    device(OTHER_USER)
    send = Sender()
    with tenant.as_user(OTHER_USER):
        push.run_notify(NINE_LA, send=send, create_task=lambda *a: True)
    assert send.sent == []


def test_daily_run_schedules_shared_heads_up_with_the_share_partition(monkeypatch):
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    due_child()
    device(TEST_USER)
    made = []
    monkeypatch.setattr("app.tasks.create_task", lambda *a: made.append(tenant.partition()) or True)
    with tenant.as_user(TEST_USER):
        push.run_notify(NINE_LA, send=Sender())
    assert made == [SHARE]


def test_shared_heads_up_fans_out_to_members_with_mounts(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", f"{TEST_USER};{OTHER_USER};third@example.com")
    from zoneinfo import ZoneInfo
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    soon = (dt.datetime.now(ZoneInfo("America/Los_Angeles")) + dt.timedelta(hours=2)).replace(
        tzinfo=None, second=0, microsecond=0)
    due_child(soon.isoformat())
    for email in (TEST_USER, OTHER_USER, "third@example.com"):
        device(email)
    send = Sender()
    monkeypatch.setattr(push, "send_fcm", send)
    out = notifications.notify_todo(push.HeadsUp(todo_id=CHILD, due=soon.isoformat(),
                                                 user=TEST_USER, partition=SHARE))
    assert out["sent"] == 2
    assert {t for t, _, _ in send.sent} == {f"tok-{TEST_USER}", f"tok-{OTHER_USER}"}


def test_heads_up_for_an_unshared_share_is_silent():
    make_share(TEST_USER, state="unshared", returned_to=TEST_USER)
    out = notifications.notify_todo(push.HeadsUp(todo_id=CHILD, due="x", user=TEST_USER, partition=SHARE))
    assert out == {"sent": 0, "skipped": "stale"}
