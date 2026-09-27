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
