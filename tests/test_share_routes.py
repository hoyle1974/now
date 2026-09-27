"""Requests on a shared item: X-Share binding, permissions, view state."""
import pytest
from fastapi.testclient import TestClient

from app import blobstore, db, shares, tenant
from app.main import app
from tests.helpers import OTHER_USER, TEST_USER, act_as, wipe_users
from tests.share_fixtures import CHILD, ROOT, make_share

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


def _share_doc(todo_id):
    with tenant.as_user(TEST_USER), tenant.as_partition(f"shares/{ROOT}"):
        return db.get_todo(todo_id)


def test_member_rw_can_patch_child():
    make_share(TEST_USER, mode="rw")
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{CHILD}", json={"title": "Book the hotel"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.headers["X-Partition"] == f"shares/{ROOT}"
    assert r.json()["last_edited_by"] == OTHER_USER
    assert _share_doc(CHILD).title == "Book the hotel"


def test_member_can_read_child_through_the_share():
    make_share(TEST_USER, mode="ro")
    act_as(app, OTHER_USER)
    assert client.get(f"/todos/{CHILD}", headers=H).json()["title"] == "Book hotel"


def test_member_ro_patch_is_403_read_only():
    make_share(TEST_USER, mode="ro")
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{CHILD}", json={"done": True}, headers=H)
    assert r.status_code == 403 and r.json()["detail"] == "read only"
    assert _share_doc(CHILD).done is False


def test_member_ro_split_and_delete_are_403():
    make_share(TEST_USER, mode="ro")
    act_as(app, OTHER_USER)
    assert client.post(f"/todos/{ROOT}/split", json={"descriptions": ["x"]}, headers=H).json()["detail"] == "read only"
    assert client.delete(f"/todos/{CHILD}", headers=H).status_code == 403


def test_owner_writes_a_read_only_share():
    make_share(TEST_USER, mode="ro")
    act_as(app, TEST_USER)
    assert client.patch(f"/todos/{CHILD}", json={"done": True}, headers=H).status_code == 200


def test_ro_member_collapse_goes_to_view_state():
    make_share(TEST_USER, mode="ro")
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{ROOT}", json={"collapsed": True}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["collapsed"] is True
    assert _share_doc(ROOT).collapsed is False
    assert shares.get_view_state(OTHER_USER, ROOT) == {ROOT}


def test_non_member_gets_share_revoked():
    make_share(TEST_USER, members=[TEST_USER])
    act_as(app, OTHER_USER)
    r = client.get(f"/todos/{CHILD}", headers=H)
    assert r.status_code == 403 and r.json()["detail"] == "share revoked"


def test_missing_share_is_share_revoked():
    act_as(app, OTHER_USER)
    assert client.get(f"/todos/{CHILD}", headers=H).json()["detail"] == "share revoked"


def test_unshared_share_is_revoked_for_members():
    make_share(TEST_USER, state="unshared", returned_to=TEST_USER)
    act_as(app, OTHER_USER)
    assert client.patch(f"/todos/{CHILD}", json={"title": "x"}, headers=H).json()["detail"] == "share revoked"


def test_rw_member_cannot_delete_or_move_the_root():
    make_share(TEST_USER, mode="rw")
    act_as(app, OTHER_USER)
    r = client.delete(f"/todos/{ROOT}", headers=H)
    assert r.status_code == 403 and r.json()["detail"] == "owner only"
    r = client.patch(f"/todos/{ROOT}/reparent", json={"parent_id": None, "index": 0}, headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "crosses share boundary"


def test_owner_can_delete_the_root():
    make_share(TEST_USER, mode="rw")
    act_as(app, TEST_USER)
    assert client.delete(f"/todos/{ROOT}", headers=H).status_code == 204


def test_bad_share_header_is_400():
    act_as(app, OTHER_USER)
    assert client.get(f"/todos/{CHILD}", headers={"X-Share": "../users/x"}).status_code == 400


def test_sharing_disabled_rejects_x_share(monkeypatch):
    monkeypatch.delenv("SHARING_ENABLED")
    make_share(TEST_USER)
    act_as(app, OTHER_USER)
    r = client.get(f"/todos/{CHILD}", headers=H)
    assert r.status_code == 404 and r.json()["detail"] == "sharing disabled"


def test_blocked_by_across_partitions_is_refused():
    make_share(TEST_USER, mode="rw")
    act_as(app, OTHER_USER)
    mine = client.post("/todos", json={"title": "private"}).json()["todo_id"]
    r = client.patch(f"/todos/{CHILD}", json={"blocked_by": [mine]}, headers=H)
    assert r.status_code == 400


# ---- share / unshare / mode (Task 7) ---------------------------------------------

def _mk(title, parent=None, **kw):
    body = {"title": title, **kw}
    if parent is None:
        return client.post("/todos", json=body).json()["todo_id"]
    r = client.post(f"/todos/{parent}/split", json={"descriptions": [title], **kw})
    return r.json()["affected"][1]["todo_id"]


def _mine(email=TEST_USER):
    return {d.id: d.to_dict() for d in db.user_ref(email).collection("todos").stream()}


def test_share_route_migrates_and_returns_share():
    act_as(app, TEST_USER)
    root = _mk("Trip", type="list")
    child = _mk("Book hotel", root)
    r = client.put(f"/todos/{root}/share", json={"mode": "rw"})
    assert r.status_code == 200, r.text
    assert r.json()["share"] == {"id": root, "owner": TEST_USER, "mode": "rw", "state": "active"}
    assert _mine()[root]["type"] == "mount" and child not in _mine()
    assert client.get(f"/todos/{child}", headers={"X-Share": root}).json()["title"] == "Book hotel"


def test_share_route_refuses_calendar_subtree_and_ineligible_types():
    act_as(app, TEST_USER)
    root = _mk("Trip", type="list")
    _mk("Cal", root, type="calendar")
    r = client.put(f"/todos/{root}/share", json={"mode": "rw"})
    assert r.status_code == 409 and r.json()["detail"] == "crosses share boundary"
    cal = _mk("Cal2", type="calendar")
    assert client.put(f"/todos/{cal}/share", json={"mode": "rw"}).json()["detail"] == "not eligible"


def test_share_routes_are_404_when_disabled(monkeypatch):
    monkeypatch.delenv("SHARING_ENABLED")
    act_as(app, TEST_USER)
    root = _mk("Trip", type="list")
    assert client.put(f"/todos/{root}/share", json={"mode": "rw"}).status_code == 404
    assert client.get("/shares").status_code == 404


def test_mode_change_by_owner_only():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    assert client.put(f"/todos/{ROOT}/share", json={"mode": "ro"}).json()["detail"] == "owner only"
    act_as(app, TEST_USER)
    assert client.put(f"/todos/{ROOT}/share", json={"mode": "ro"}).status_code == 200
    assert shares.get(ROOT).mode == "ro"


def test_unshare_route_brings_items_home():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    assert client.delete(f"/todos/{ROOT}/share").json()["detail"] == "owner only"
    act_as(app, TEST_USER)
    assert client.delete(f"/todos/{ROOT}/share").status_code == 200
    mine = _mine()
    assert mine[ROOT]["type"] == "list" and CHILD in mine
    assert shares.get(ROOT).state == "unshared"


def test_get_shares_lists_active_for_member():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER,))
    act_as(app, OTHER_USER)
    body = client.get("/shares").json()
    assert body["items"] == [{"id": ROOT, "title": "Trip", "owner": TEST_USER, "mode": "ro",
                              "mounted": False, "removed": False}]


# ---- edits addressed to an item's old home ---------------------------------------

def test_content_op_on_mount_is_redirected_to_share():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    act_as(app, TEST_USER)
    r = client.patch(f"/todos/{ROOT}", json={"title": "Portland trip"})
    assert r.status_code == 200, r.text
    assert r.headers["X-Partition"] == f"shares/{ROOT}"
    assert _share_doc(ROOT).title == "Portland trip"
    assert _mine()[ROOT]["type"] == "mount" and _mine()[ROOT]["title"] == ""


def test_edit_from_a_stale_device_lands_in_the_share():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER,))
    act_as(app, TEST_USER)
    r = client.patch(f"/todos/{CHILD}", json={"done": True})  # no X-Share: the old home
    assert r.status_code == 200 and r.headers["X-Partition"] == f"shares/{ROOT}"
    assert _share_doc(CHILD).done is True


def test_replay_of_pre_share_commit_is_not_reapplied():
    act_as(app, TEST_USER)
    root = _mk("Trip", type="list")
    child = _mk("Book hotel", root)
    first = client.patch(f"/todos/{child}", json={"title": "v2"}, headers={"X-Txn-Id": "t1"})
    assert client.put(f"/todos/{root}/share", json={"mode": "rw"}).status_code == 200
    again = client.patch(f"/todos/{child}", json={"title": "v2"}, headers={"X-Txn-Id": "t1"})
    assert again.status_code == 200 and again.json() == first.json()
    with tenant.as_user(TEST_USER), tenant.as_partition(f"shares/{root}"):
        assert db.get_todo(child).version == first.json()["version"]


def test_owner_x_share_op_after_unshare_lands_home():
    make_share(TEST_USER, state="unshared", returned_to=TEST_USER)
    act_as(app, TEST_USER)
    mine = _mk("Book hotel home")
    r = client.patch(f"/todos/{mine}", json={"done": True}, headers=H)
    assert r.status_code == 200 and r.headers["X-Partition"] == f"users/{TEST_USER}"


def test_member_edit_after_item_left_the_share_is_not_found():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, TEST_USER)
    assert client.patch(f"/todos/{CHILD}/reparent", headers=H,
                        json={"parent_id": None, "index": 0, "parent_share": None}).status_code == 200
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{CHILD}", json={"title": "x"}, headers=H)
    assert r.status_code == 404 and r.json()["detail"] == "todo not found"


# ---- moving across the edge -------------------------------------------------------

def test_cross_edge_reparent_in_and_out():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    cake = _mk("Buy cake")
    r = client.patch(f"/todos/{cake}/reparent", json={"parent_id": ROOT, "index": 0, "parent_share": ROOT})
    assert r.status_code == 200, r.text
    assert r.headers["X-Partition"] == f"shares/{ROOT}"
    assert _share_doc(cake).parent_id is not None and cake not in _mine(OTHER_USER)
    r = client.patch(f"/todos/{CHILD}/reparent", headers=H,
                     json={"parent_id": None, "index": 0, "parent_share": None})
    assert r.status_code == 200 and CHILD in _mine(OTHER_USER)


def test_ro_member_cannot_drag_in():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    cake = _mk("Buy cake")
    r = client.patch(f"/todos/{cake}/reparent", json={"parent_id": ROOT, "index": 0, "parent_share": ROOT})
    assert r.status_code == 403 and r.json()["detail"] == "read only"


def test_mount_cannot_be_reparented_into_share():
    make_share(TEST_USER, mode="rw", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{ROOT}/reparent", json={"parent_id": CHILD, "index": 0, "parent_share": ROOT})
    assert r.status_code == 409 and r.json()["detail"] == "crosses share boundary"


def test_mount_moves_are_last_write_wins_and_removable():
    make_share(TEST_USER, mode="ro", mount_for=(TEST_USER, OTHER_USER))
    act_as(app, OTHER_USER)
    mine = _mk("Home")
    r = client.patch(f"/todos/{ROOT}/reparent", json={"parent_id": mine, "index": 0}, headers={"If-Match": "99"})
    assert r.status_code == 200, r.text
    assert _mine(OTHER_USER)[ROOT]["parent_id"] == mine
    assert client.delete(f"/todos/{ROOT}").status_code == 204
    assert _mine(OTHER_USER)[ROOT]["deleted"] is True
    assert client.patch(f"/todos/{ROOT}/undelete").status_code == 200
    assert shares.get(ROOT).state == "active"
