"""Tests for "Clear completed" and the trash (list + undelete)."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import db, tenant
from tests.helpers import TEST_USER, act_as, wipe_users

client = TestClient(app)


@pytest.fixture
def db_setup():
    act_as(app)
    db.init()
    wipe_users()
    token = tenant.set_user(TEST_USER)
    yield 0
    tenant.reset(token)
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


def test_trash_lists_every_item_including_those_inside_a_deleted_parent(db_setup):
    work = _mk("Work")
    task = _mk("Submit PR", parent=work, done=True)
    sub = _mk("sub", parent=task)
    other = _mk("other")
    client.delete(f"/todos/{other}")
    client.delete(f"/todos/{work}")
    items = client.get("/todos/trash").json()["items"]
    assert [(t["title"], t["deleted_with"]) for t in items] == [
        ("Work", None), ("Submit PR", "Work"), ("sub", "Work"), ("other", None)]
    assert items[1]["type"] == "todo" and items[1]["done"] is True
    parse = dt.datetime.fromisoformat
    assert parse(items[1]["trashed_at"]) == parse(items[0]["deleted_at"])   # inside a parent: the parent's date


def test_an_item_deleted_earlier_is_not_repeated_under_a_later_parent(db_setup):
    work = _mk("Work")
    task = _mk("task", parent=work)
    client.delete(f"/todos/{task}")
    client.delete(f"/todos/{work}")
    items = client.get("/todos/trash").json()["items"]
    assert sorted(t["title"] for t in items) == ["Work", "task"]
    assert [t["deleted_with"] for t in items if t["title"] == "task"] == [None]


def test_restoring_an_inner_item_restores_its_parent_chain_and_leaves_siblings_in_trash(db_setup):
    top = _mk("top")
    mid = _mk("mid", parent=top)
    leaf = _mk("leaf", parent=mid)
    other = _mk("other", parent=mid)          # sibling of leaf, deleted with the chain
    aunt = _mk("aunt", parent=top)            # sibling of mid
    client.delete(f"/todos/{top}")
    res = client.patch(f"/todos/{leaf}/undelete")
    assert res.status_code == 200
    assert {a["todo_id"] for a in res.json()["affected"]} == {leaf, top}   # mid was never flagged
    by_id = client.get("/todos/tree").json()["todosById"]
    assert {top, mid, leaf} <= set(by_id) and other not in by_id and aunt not in by_id
    assert by_id[leaf]["parent_id"] == mid and by_id[mid]["parent_id"] == top   # still nested
    assert sorted(t["title"] for t in client.get("/todos/trash").json()["items"]) == ["aunt", "other"]


def test_restoring_the_top_of_a_deleted_subtree_brings_everything_back(db_setup):
    top = _mk("top")
    a = _mk("a", parent=top)
    client.delete(f"/todos/{top}")
    assert client.patch(f"/todos/{top}/undelete").status_code == 200
    assert {top, a} <= set(client.get("/todos/tree").json()["todosById"])
    assert client.get("/todos/trash").json()["items"] == []


def test_restoring_under_an_archived_ancestor_goes_to_the_top_level(db_setup):
    top = _mk("top")
    leaf = _mk("leaf", parent=top)
    client.delete(f"/todos/{top}")
    db.user_ref(TEST_USER).collection("todos").document(top).delete()      # as if archived
    assert client.patch(f"/todos/{leaf}/undelete").status_code == 200
    by_id = client.get("/todos/tree").json()["todosById"]
    assert by_id[leaf]["parent_id"] is None


def test_trash_is_paged_with_a_hard_cap(db_setup):
    ids = [_mk(f"t{i}") for i in range(5)]
    for i in ids:
        client.delete(f"/todos/{i}")
    first = client.get("/todos/trash?limit=2").json()
    assert len(first["items"]) == 2 and first["has_more"] is True and first["next_offset"] == 2
    second = client.get("/todos/trash?limit=2&offset=2").json()
    last = client.get("/todos/trash?limit=2&offset=4").json()
    assert len(second["items"]) == 2 and second["has_more"] is True
    assert len(last["items"]) == 1 and last["has_more"] is False
    everyone = [t["title"] for r in (first, second, last) for t in r["items"]]
    assert sorted(everyone) == [f"t{i}" for i in range(5)] and len(set(everyone)) == 5
    assert client.get("/todos/trash?limit=101").status_code == 422      # hard cap
    assert client.get("/todos/trash?limit=0").status_code == 422


def test_trash_search_matches_title_case_and_accents_across_pages(db_setup):
    for title in ("Caf\u00e9 plans", "Submit PR", "more cafe stuff"):
        client.delete(f"/todos/{_mk(title)}")
    hits = client.get("/todos/trash?q=CAFE").json()
    assert sorted(t["title"] for t in hits["items"]) == ["Caf\u00e9 plans", "more cafe stuff"]
    assert [t["title"] for t in client.get("/todos/trash?q=submit pr").json()["items"]] == ["Submit PR"]
    assert client.get("/todos/trash?q=nothing").json()["items"] == []
    paged = client.get("/todos/trash?q=cafe&limit=1").json()
    assert len(paged["items"]) == 1 and paged["has_more"] is True


def test_undelete_of_cleared_parent_brings_its_done_subtree_back(db_setup):
    c = _mk("c", done=True)
    c1 = _mk("c1", parent=c, done=True)
    client.post("/todos/clear-completed")
    assert _live_ids() == set()
    client.patch(f"/todos/{c}/undelete")
    assert _live_ids() == {c, c1}


def test_undelete_with_deleted_parent_restores_the_parent_too(db_setup):
    p = _mk("p")
    k = _mk("k", parent=p)
    client.delete(f"/todos/{k}")
    client.delete(f"/todos/{p}")
    r = client.patch(f"/todos/{k}/undelete")
    assert r.status_code == 200 and r.json()["parent_id"] == p
    assert [t["todo_id"] for t in client.get("/todos/tree").json()["roots"]] == [p]
    assert client.get("/todos/trash").json()["items"] == []


def test_undelete_with_deleted_grandparent_restores_the_whole_chain(db_setup):
    g = _mk("g")
    p = _mk("p", parent=g)
    k = _mk("k", parent=p)
    client.delete(f"/todos/{k}")
    client.delete(f"/todos/{p}")
    client.delete(f"/todos/{g}")
    r = client.patch(f"/todos/{k}/undelete")
    assert r.json()["parent_id"] == p
    assert {g, p, k} <= _live_ids()


def test_undelete_with_live_parent_keeps_parent(db_setup):
    p = _mk("p")
    k = _mk("k", parent=p)
    client.delete(f"/todos/{k}")
    r = client.patch(f"/todos/{k}/undelete")
    assert r.json()["parent_id"] == p
