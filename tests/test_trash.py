"""Tests for "Clear completed" and the trash (list + undelete)."""

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user
from app.main import app
from app import db

app.dependency_overrides[require_user] = lambda: None
client = TestClient(app)


@pytest.fixture
def db_setup():
    db.init()
    for name in ("todos", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield 0
    db.teardown()


def rev_of(response):
    return int(response.headers["x-rev"])


def _mk(title, parent=None, done=False):
    t = client.post("/todos", json={"title": title}).json()["todo_id"]
    if parent:
        client.patch(f"/todos/{t}/reparent", json={"parent_id": parent, "index": None})
    if done:
        client.patch(f"/todos/{t}", json={"done": True})
    return t


def _live_ids():
    return set(client.get("/todos/tree").json()["todosById"].keys())


def test_clear_completed_only_fully_done_subtrees(db_setup):
    a = _mk("a", done=True)                    # done, no kids: cleared
    b = _mk("b", done=True)                    # done with an unfinished kid: kept
    b1 = _mk("b1", parent=b)
    c = _mk("c", done=True)                    # done, all kids done: cleared as one
    _mk("c1", parent=c, done=True)
    d = _mk("d")                               # not done: kept
    d1 = _mk("d1", parent=d, done=True)        # done leaf under a kept parent: cleared
    r = client.post("/todos/clear-completed")
    assert r.status_code == 200
    cleared = {x["todo_id"] for x in r.json()["cleared"]}
    assert cleared == {a, c, d1}
    assert _live_ids() == {b, b1, d}
    assert client.get("/todos/tree").json()["todosById"][d]["child_ids"] == []


def test_clear_completed_is_idempotent_and_bumps_rev_once(db_setup):
    a = _mk("a", done=True)
    _mk("b", done=True)
    before = client.get("/todos/rev").json()["rev"]
    h = {"X-Txn-Id": "clr-1"}
    r1 = client.post("/todos/clear-completed", headers=h)
    r2 = client.post("/todos/clear-completed", headers=h)
    assert r1.json() == r2.json()
    assert rev_of(r1) == before + 1
    assert client.get("/todos/rev").json()["rev"] == before + 1
    assert a in {x["todo_id"] for x in r1.json()["cleared"]}
    assert all(x["version"] == 3 for x in r1.json()["cleared"])


def test_clear_completed_with_nothing_does_not_bump_rev(db_setup):
    _mk("a")
    before = client.get("/todos/rev").json()["rev"]
    r = client.post("/todos/clear-completed")
    assert r.json()["cleared"] == []
    assert client.get("/todos/rev").json()["rev"] == before


def test_trash_lists_deleted_and_undelete_restores(db_setup):
    a = _mk("a", done=True)
    b = _mk("b")
    client.post("/todos/clear-completed")
    items = client.get("/todos/trash").json()["items"]
    assert [t["todo_id"] for t in items] == [a]
    assert client.patch(f"/todos/{a}/undelete").status_code == 200
    assert client.get("/todos/trash").json()["items"] == []
    assert _live_ids() == {a, b}


def test_trash_lists_most_recently_deleted_first(db_setup):
    a, b, c = _mk("a"), _mk("b"), _mk("c")      # created a, b, c
    for todo in (b, c, a):                        # deleted b, then c, then a
        client.delete(f"/todos/{todo}")
    items = client.get("/todos/trash").json()["items"]
    assert [t["title"] for t in items] == ["a", "c", "b"]


def test_undelete_of_cleared_parent_brings_its_done_subtree_back(db_setup):
    c = _mk("c", done=True)
    c1 = _mk("c1", parent=c, done=True)
    client.post("/todos/clear-completed")
    assert _live_ids() == set()
    client.patch(f"/todos/{c}/undelete")
    assert _live_ids() == {c, c1}


def test_undelete_with_deleted_parent_goes_to_top_level(db_setup):
    p = _mk("p")
    k = _mk("k", parent=p)
    client.delete(f"/todos/{k}")
    client.delete(f"/todos/{p}")
    r = client.patch(f"/todos/{k}/undelete")
    assert r.status_code == 200 and r.json()["parent_id"] is None
    assert [t["todo_id"] for t in client.get("/todos/tree").json()["roots"]] == [k]


def test_undelete_with_deleted_grandparent_goes_to_top_level(db_setup):
    g = _mk("g")
    p = _mk("p", parent=g)
    k = _mk("k", parent=p)
    client.delete(f"/todos/{k}")
    client.delete(f"/todos/{g}")
    r = client.patch(f"/todos/{k}/undelete")
    assert r.json()["parent_id"] is None
    assert k in _live_ids()


def test_undelete_with_live_parent_keeps_parent(db_setup):
    p = _mk("p")
    k = _mk("k", parent=p)
    client.delete(f"/todos/{k}")
    r = client.patch(f"/todos/{k}/undelete")
    assert r.json()["parent_id"] == p
