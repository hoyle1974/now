"""What members see: shares spliced into their tree, revs, Next up, trash, cleanup."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app import blobstore, db, shares, tenant
from app.main import app
from tests.helpers import OTHER_USER, TEST_USER, act_as, wipe_users
from tests.share_fixtures import CHILD, ROOT, add_mount, make_share

client = TestClient(app)
H = {"X-Share": ROOT}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("SHARING_ENABLED", "1")
    db.init()
    wipe_users()
    blobstore.use_memory()
    yield
    app.dependency_overrides.clear()
    db.teardown()


def tree(email=OTHER_USER):
    act_as(app, email)
    return client.get("/todos/tree").json()


def test_member_tree_contains_spliced_share_at_mount_position():
    act_as(app, OTHER_USER)
    home = client.post("/todos", json={"title": "Home", "type": "list"}).json()["todo_id"]
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    add_mount(OTHER_USER, parent_id=home, order_idx=0)
    t = tree()
    assert [r["todo_id"] for r in t["roots"]] == [home]
    assert t["todosById"][home]["child_ids"] == [ROOT]
    root = t["todosById"][ROOT]
    assert root["title"] == "Trip" and root["type"] == "list" and root["parent_id"] == home
    assert root["share_root"] is True and root["child_ids"] == [CHILD]
    assert t["todosById"][CHILD]["title"] == "Book hotel"


def test_every_share_node_is_tagged():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER, OTHER_USER))
    t = tree()
    tag = {"id": ROOT, "mode": "ro", "owner": TEST_USER}
    assert t["todosById"][ROOT]["share"] == tag and t["todosById"][CHILD]["share"] == tag
    assert t["todosById"][CHILD]["share_root"] is False


def test_view_state_overlays_collapsed():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    client.patch(f"/todos/{ROOT}", json={"collapsed": True}, headers=H)
    assert tree()["todosById"][ROOT]["collapsed"] is True
    assert tree(TEST_USER)["todosById"][ROOT]["collapsed"] is False


def test_new_user_gets_mount_and_new_shares_entry():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    t = tree()
    assert t["new_shares"] == [{"id": ROOT, "title": "Trip", "owner": TEST_USER}]
    assert [r["todo_id"] for r in t["roots"]] == [ROOT]
    assert tree()["new_shares"] == []
    assert tree(TEST_USER)["new_shares"] == []


def test_removed_mount_is_not_recreated():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    add_mount(OTHER_USER, deleted=True)
    t = tree()
    assert t["new_shares"] == [] and ROOT not in t["todosById"]


def test_unshared_mount_is_hidden():
    act_as(app, OTHER_USER)
    home = client.post("/todos", json={"title": "Home", "type": "list"}).json()["todo_id"]
    make_share(TEST_USER, mode="rw", state="unshared", returned_to=TEST_USER)
    add_mount(OTHER_USER, parent_id=home)
    t = tree()
    assert ROOT not in t["todosById"] and CHILD not in t["todosById"]
    assert t["todosById"][home]["child_ids"] == []


def test_mount_of_a_vanished_share_is_cleaned_up():
    add_mount(OTHER_USER)
    assert ROOT not in tree()["todosById"]
    assert not db.user_ref(OTHER_USER).collection("todos").document(ROOT).get().exists


def test_deleted_root_hides_mounts_and_restore_brings_them_back():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, TEST_USER)
    assert client.delete(f"/todos/{ROOT}", headers=H).status_code == 204
    assert ROOT not in tree()["todosById"]
    act_as(app, TEST_USER)
    assert client.patch(f"/todos/{ROOT}/undelete", headers=H).status_code == 200
    assert ROOT in tree()["todosById"]


def test_sharing_disabled_hides_mounts(monkeypatch):
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    monkeypatch.delenv("SHARING_ENABLED")
    t = tree()
    assert ROOT not in t["todosById"] and t["roots"] == []


def test_revs_include_each_mounted_share_and_meta():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    t = tree()
    act_as(app, OTHER_USER)
    polled = client.get("/todos/rev").json()["revs"]
    assert set(polled) == {f"users/{OTHER_USER}", "shares", f"shares/{ROOT}"}
    assert polled == t["revs"]


def test_share_write_moves_member_rev_map():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    before = client.get("/todos/rev").json()["revs"]
    act_as(app, TEST_USER)
    client.patch(f"/todos/{CHILD}", json={"done": True}, headers=H)
    act_as(app, OTHER_USER)
    after = client.get("/todos/rev").json()["revs"]
    assert after[f"shares/{ROOT}"] > before[f"shares/{ROOT}"]
    assert after[f"users/{OTHER_USER}"] == before[f"users/{OTHER_USER}"]


def test_next_up_includes_shared_due_items_for_every_member():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, TEST_USER)
    client.patch(f"/todos/{CHILD}", json={"due_date": "2026-01-01T09:00:00"}, headers=H)
    for email in (TEST_USER, OTHER_USER):
        act_as(app, email)
        items = client.get("/todos/next").json()["items"]
        assert CHILD in [i["todo_id"] for i in items], email


def test_trash_includes_rw_share_trash_tagged():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    mine = client.post("/todos", json={"title": "mine"}).json()["todo_id"]
    client.delete(f"/todos/{mine}")
    client.delete(f"/todos/{CHILD}", headers=H)
    items = client.get("/todos/trash").json()["items"]
    by_id = {i["todo_id"]: i for i in items}
    assert set(by_id) == {mine, CHILD}
    assert by_id[CHILD]["share"] == {"id": ROOT, "mode": "rw", "owner": TEST_USER}
    assert by_id[mine]["share"] is None


def test_ro_member_trash_excludes_share_and_removed_mounts_are_not_trash():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, TEST_USER)
    client.delete(f"/todos/{CHILD}", headers=H)
    act_as(app, OTHER_USER)
    client.delete(f"/todos/{ROOT}")  # remove the mount
    assert client.get("/todos/trash").json()["items"] == []


def test_prune_txn_log_covers_shares():
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)
    db.partition_ref(f"shares/{ROOT}").collection("txn_log").document("old").set({"created_at": old})
    assert db.prune_txn_log() == 1


def test_tombstone_swept_after_30_days():
    make_share(TEST_USER, mode="rw", state="unshared", returned_to=TEST_USER)
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=31)
    db.get_conn().collection("shares").document(ROOT).update({"updated_at": old})
    with tenant.as_user(TEST_USER):
        assert shares.sweep() == 1
    assert shares.get(ROOT) is None
    assert list(db.partition_ref(f"shares/{ROOT}").collection("todos").stream()) == []


def test_share_whose_root_was_archived_ends():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    with tenant.as_user(TEST_USER), tenant.as_partition(f"shares/{ROOT}"):
        db.partition_ref().collection("todos").document(ROOT).delete()
        db.partition_ref().collection("todos").document(CHILD).delete()
        assert shares.sweep() == 1
    assert shares.get(ROOT) is None
