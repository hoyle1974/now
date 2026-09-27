"""Findings from the Cursor review of the sharing feature (2026-09-27)."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app import blobstore, db, migrate, models, push, shares, tenant
from app.main import app
from tests.helpers import OTHER_USER, TEST_USER, act_as, wipe_users
from tests.share_fixtures import CHILD, ROOT, add_mount, make_share

client = TestClient(app)
H = {"X-Share": ROOT}
SHARE = f"shares/{ROOT}"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("SHARING_ENABLED", "1")
    db.init()
    wipe_users()
    blobstore.use_memory()
    yield
    app.dependency_overrides.clear()
    db.teardown()


def share_doc(todo_id, deleted=False):
    with tenant.as_user(TEST_USER), tenant.as_partition(SHARE):
        return (db.get_deleted_todo if deleted else db.get_todo)(models.TodoId(todo_id))


def share_roots():
    with tenant.as_user(TEST_USER), tenant.as_partition(SHARE):
        return [str(d.id) for d in db.partition_ref().collection("todos").where("parent_id", "==", None).stream()]


# ---- 1. only the owner deletes the share root, whatever the route --------------------

def test_rw_member_cannot_delete_root_with_a_patch():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{ROOT}", json={"deleted": True}, headers=H)
    assert r.status_code == 403 and r.json()["detail"] == "owner only"
    assert share_doc(ROOT) is not None


def test_clear_completed_inside_a_share_clears_done_items_but_never_the_root():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    client.patch(f"/todos/{CHILD}", json={"done": True}, headers=H)  # now everything in the share is done
    r = client.post("/todos/clear-completed", headers=H)
    assert r.status_code == 200, r.text
    assert [c["todo_id"] for c in r.json()["cleared"]] == [CHILD]
    assert share_doc(ROOT) is not None and share_doc(CHILD) is None


def test_read_only_member_cannot_clear_a_share():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER, OTHER_USER))
    with tenant.as_user(TEST_USER), tenant.as_partition(SHARE):
        t = db.get_todo(models.TodoId(CHILD))
        t.done = True
        db.run_atomic(None, lambda: (db.update_todo(t), (200, None))[-1])
    act_as(app, OTHER_USER)
    assert client.post("/todos/clear-completed", headers=H).status_code == 403
    assert share_doc(CHILD) is not None


# ---- 3. no second top-level item in a share --------------------------------------------

def test_reparent_to_the_top_inside_a_share_is_refused():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{CHILD}/reparent", json={"parent_id": None, "index": 0}, headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "crosses share boundary"
    assert share_roots() == [ROOT]


def test_repeating_share_root_is_refused_not_orphaned():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    act_as(app, TEST_USER)
    client.patch(f"/todos/{ROOT}", json={"type": "todo", "repeat": {"unit": "day", "every": 1},
                                          "due_date": "2026-09-27T09:00:00"}, headers=H)
    r = client.post(f"/todos/{ROOT}/repeat", json={}, headers=H)
    assert r.status_code == 400
    assert share_roots() == [ROOT]


def test_repeating_child_in_a_share_still_repeats_as_a_sibling():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    act_as(app, TEST_USER)
    client.patch(f"/todos/{CHILD}", json={"repeat": {"unit": "day", "every": 1},
                                           "due_date": "2026-09-27T09:00:00"}, headers=H)
    r = client.post(f"/todos/{CHILD}/repeat", json={}, headers=H)
    assert r.status_code == 200 and r.json()["created"] is True
    assert share_doc(r.json()["spawned_id"]).parent_id == models.TodoId(ROOT)


# ---- 4. a crash between the freeze and the share record still finishes -----------------

def test_share_resumes_when_the_share_record_was_never_written(monkeypatch):
    act_as(app, TEST_USER)
    root = client.post("/todos", json={"title": "Trip", "type": "list"}).json()["todo_id"]
    real = shares.put
    monkeypatch.setattr(shares, "put", lambda s: (_ for _ in ()).throw(RuntimeError("died")))
    with tenant.as_user(TEST_USER), pytest.raises(RuntimeError):
        migrate.migrate_subtree(f"users/{TEST_USER}", root, f"shares/{root}", kind="share", mode="rw")
    monkeypatch.setattr(shares, "put", real)
    past = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)).isoformat()
    db.partition_ref(f"users/{TEST_USER}").collection("meta").document("rev").update({"migrating.lease_until": past})
    assert migrate.resume_if_stale(f"users/{TEST_USER}") is True
    got = shares.get(root)
    assert got is not None and got.state == "active" and got.owner == TEST_USER and got.mode == "rw"


# ---- 7. "Remove from my list" sticks past the archive window ----------------------------

def test_archive_sweep_keeps_removed_mounts():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    add_mount(OTHER_USER, deleted=True)
    old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)).isoformat()
    db.user_ref(OTHER_USER).collection("todos").document(ROOT).update({"deleted_at": old})
    with tenant.as_user(OTHER_USER):
        db.archive_expired()
        assert shares.ensure_mounts(OTHER_USER) == []
    assert db.user_ref(OTHER_USER).collection("todos").document(ROOT).get().to_dict()["deleted"] is True


# ---- 8. nothing unshareable gets into a share ---------------------------------------------

@pytest.mark.parametrize("call", [
    lambda: client.post(f"/todos/{ROOT}/split", json={"descriptions": ["Cal"], "type": "calendar"}, headers=H),
    lambda: client.patch(f"/todos/{CHILD}", json={"type": "calendar"}, headers=H),
])
def test_calendar_types_cannot_enter_a_share(call):
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    r = call()
    assert r.status_code == 409 and r.json()["detail"] == "crosses share boundary"
    assert share_doc(CHILD).type == "todo"


# ---- 14. a heads-up queued before a share finds the item ---------------------------------

def test_heads_up_for_an_item_that_moved_into_a_share_fans_out(monkeypatch):
    from zoneinfo import ZoneInfo
    from app.routes import notifications
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    soon = (datetime.datetime.now(ZoneInfo("America/Los_Angeles")) + datetime.timedelta(hours=2)).replace(
        tzinfo=None, second=0, microsecond=0)
    with tenant.as_user(TEST_USER), tenant.as_partition(SHARE):
        t = db.get_todo(models.TodoId(CHILD))
        t.due_date = soon
        db.run_atomic(None, lambda: (db.update_todo(t), (200, None))[-1])
    for email in (TEST_USER, OTHER_USER):
        with tenant.as_user(email):
            db.upsert_push_device(f"d-{email}", f"tok-{email}", "America/Los_Angeles", "ios")
    sent = []
    monkeypatch.setattr(push, "send_fcm", lambda token, p: sent.append(token))
    # Queued while the item was still in the owner's own list: no partition, or the old one.
    out = notifications.notify_todo(push.HeadsUp(todo_id=CHILD, due=soon.isoformat(), user=TEST_USER,
                                                 partition=f"users/{TEST_USER}"))
    assert out["sent"] == 2 and set(sent) == {f"tok-{TEST_USER}", f"tok-{OTHER_USER}"}


# ---- 15. a share that grew past the cap can still be unshared ------------------------------

def test_unshare_ignores_the_size_cap(monkeypatch):
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    monkeypatch.setattr(migrate, "MAX_NODES", 1)
    act_as(app, TEST_USER)
    r = client.delete(f"/todos/{ROOT}/share")
    assert r.status_code == 200, r.text
    assert shares.get(ROOT).state == "unshared"


# ---- 5. a calendar's sync time is seen by the next tree load --------------------------------

def test_mark_calendar_synced_is_seen_by_a_cached_tree():
    act_as(app, TEST_USER)
    cal = client.post("/todos", json={"title": "Cal", "type": "calendar"}).json()["todo_id"]
    with tenant.as_user(TEST_USER):
        db.get_tree()  # warm the cache
        db.mark_calendar_synced(cal, None)
        _, by_id = db.get_tree()
    assert by_id[cal].last_synced_at is not None


# ---- 13. the page can't be framed ----------------------------------------------------------

def test_security_headers():
    r = client.get("/health")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
