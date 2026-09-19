"""Tests for the todo API endpoints.

Run with: pytest test_main.py -v

Stub only -- imports and test function names are set up, bodies are
yours to fill in.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import db, models
import uuid

client = TestClient(app)

@pytest.fixture
def db_setup():
    # Fresh Firestore emulator state for every test.
    db.init()
    for name in ("todos", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield 0
    db.teardown()

@pytest.fixture
def create_test_data():
    response1 = client.post("/todos", json={"title": "test1"})

    d = response1.json()
    id = d["todo_id"]
    d["title"] = "test1"
    d["done"] = False
    d["parent_id"] = None

    response2 = client.post("/todos", json={"title": "test2"})
    parent_id = response2.json()["todo_id"]

    d["parent_id"] = parent_id
    response3 = client.patch(f"/todos/{id}/parent/{parent_id}", json=d)

    response4 = client.get(f"/todos/{id}")

    response5 = client.get(f"/todos/{parent_id}")

    response6 = client.get(f"/todos/root")

    response7 = client.post(f"/todos/{id}/split", json={"descriptions": ["a","b","c","d"]})
    yield 0
    

def test_create_todo(db_setup):
    response = client.post("/todos", json={"title": "test"})

    assert response.status_code == 200
    assert response.json()["title"] == "test"
    assert response.json()["done"] == False


def test_get_todo(db_setup):
    response1 = client.post("/todos", json={"title": "test"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test"
    assert response1.json()["done"] == False

    id = response1.json()["todo_id"]
    response2 = client.get(f"/todos/{id}")
    assert response2.status_code == 200

    assert response1.json() == response2.json()


def test_get_todo_not_found(db_setup):
    id = uuid.uuid4()
    response = client.get(f"/todos/{id}")
    assert response.status_code == 404


def test_update_todo(db_setup):
    response1 = client.post("/todos", json={"title": "test"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test"
    assert response1.json()["done"] == False
 
    d = response1.json()
    id = d["todo_id"]
    d["title"] = "test2"
    d["done"] = True
    d["parent_id"] = None

    response2 = client.patch(f"/todos/{id}", json=d)
    assert response2.status_code == 200
    d["version"] = response2.json()["version"]

    response3 = client.get(f"/todos/{id}")
    assert response3.status_code == 200

    assert response3.json() == d


def test_update_todo_not_found(db_setup):
    id = uuid.uuid4()

    d={}
    d["todo_id"] = str(id)
    d["title"] = "test2"
    d["done"] = True
    d["parent_id"] = None

    response2 = client.patch(f"/todos/{str(id)}", json=d)
    assert response2.status_code == 404

def test_split_todo(db_setup):
    response1 = client.post("/todos", json={"title": "Big Task"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "Big Task"
    assert response1.json()["done"] == False

    id = response1.json()["todo_id"]
    response2 = client.post(f"/todos/{id}/split", json={"descriptions": ["a","b","c","d"]})
    assert response2.status_code == 200


def test_update_todo_parent(db_setup):
    response1 = client.post("/todos", json={"title": "test1"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test1"
    assert response1.json()["done"] == False

    d = response1.json()
    id = d["todo_id"]
    d["title"] = "test1"
    d["done"] = False
    d["parent_id"] = None

    response2 = client.post("/todos", json={"title": "test2"})
    assert response2.status_code == 200
    assert response2.json()["title"] == "test2"
    assert response2.json()["done"] == False
    parent_id = response2.json()["todo_id"]

    d["parent_id"] = parent_id
    response3 = client.patch(f"/todos/{id}/parent/{parent_id}", json=d)
    assert response3.status_code == 200

    response4 = client.get(f"/todos/{id}")
    assert response4.status_code == 200

    # Reparenting bumps the version and gives the todo the next order_idx.
    d["version"] = response3.json()["version"]
    d["order_idx"] = response3.json()["order_idx"]
    assert response3.json() == d

    response5 = client.get(f"/todos/{parent_id}")
    assert response5.status_code == 200
    assert response5.json()["child_ids"] == [ id ]

    response6 = client.get(f"/todos/root")
    assert response6.status_code == 200
    assert response6.json()[0]["todo_id"] == parent_id


def test_split_after_failed_reparent(db_setup):
    response1 = client.post("/todos", json={"title": "test"})
    assert response1.status_code == 200
    id = response1.json()["todo_id"]

    fake_parent_id = str(uuid.uuid4())
    d = response1.json()
    d["parent_id"] = fake_parent_id
    bad_reparent = client.patch(f"/todos/{id}/parent/{fake_parent_id}", json=d)
    assert bad_reparent.status_code == 404

    response2 = client.post(f"/todos/{id}/split", json={"descriptions": ["a", "b"]})
    assert response2.status_code == 200


def test_delete_todo(db_setup):
    response1 = client.post("/todos", json={"title": "test"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test"
    assert response1.json()["done"] == False
    id = response1.json()["todo_id"]

    response2 = client.delete(f"/todos/{id}")
    assert response2.status_code == 204

    response3 = client.get(f"/todos/{id}")
    assert response3.status_code == 404

def test_print(db_setup, create_test_data):
    response = client.get("/todos/print")
    assert response.status_code == 200


def test_root_serves_frontend_shell(db_setup):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Todos</title>" in response.text




def test_done_does_not_cascade_to_children(db_setup):
    parent = client.post("/todos", json={"title": "parent"}).json()["todo_id"]
    kids = []
    for name in ("a", "b", "c"):
        kid = client.post("/todos", json={"title": name}).json()["todo_id"]
        client.patch(f"/todos/{kid}/parent/{parent}", json={})
        kids.append(kid)

    client.patch(f"/todos/{kids[0]}", json={"done": True})
    client.patch(f"/todos/{kids[1]}", json={"done": True})
    client.patch(f"/todos/{parent}", json={"done": True})
    client.patch(f"/todos/{parent}", json={"done": False})

    done = [client.get(f"/todos/{k}").json()["done"] for k in kids]
    assert done == [True, True, False]


def test_version_starts_at_1_and_bumps_on_patch(db_setup):
    t = client.post("/todos", json={"title": "a"}).json()
    assert t["version"] == 1
    r = client.patch(f"/todos/{t['todo_id']}", json={"done": True})
    assert r.json()["version"] == 2
    assert client.get(f"/todos/{t['todo_id']}").json()["version"] == 2


def test_legacy_doc_without_version_reads_as_1_and_bumps_to_2(db_setup):
    id = str(uuid.uuid4())
    db.get_conn().collection("todos").document(id).set({
        "todo_id": id, "title": "old", "done": False,
        "create_date": "2026-01-01T00:00:00", "due_date": None,
        "order_idx": None, "parent_id": None, "deleted": False})
    assert client.get(f"/todos/{id}").json()["version"] == 1
    r = client.patch(f"/todos/{id}", json={"done": True}, headers={"If-Match": "1"})
    assert r.status_code == 200 and r.json()["version"] == 2


def test_move_bumps_only_moved_node(db_setup):
    parent = client.post("/todos", json={"title": "p"}).json()
    client.post(f"/todos/{parent['todo_id']}/split", json={"descriptions": ["a", "b"]})
    kids = client.get(f"/todos/{parent['todo_id']}").json()["child_ids"]
    r = client.patch(f"/todos/{kids[0]}/move/down")
    assert r.status_code == 200 and r.json()["version"] == 2
    assert client.get(f"/todos/{kids[1]}").json()["version"] == 1
    assert client.get(f"/todos/{parent['todo_id']}").json()["child_ids"] == [kids[1], kids[0]]


def test_if_match_stale_returns_409_with_current(db_setup):
    t = client.post("/todos", json={"title": "a"}).json()
    id = t["todo_id"]
    client.patch(f"/todos/{id}", json={"done": True})  # version -> 2
    r = client.patch(f"/todos/{id}", json={"title": "x"}, headers={"If-Match": "1"})
    assert r.status_code == 409
    assert r.json()["version"] == 2 and r.json()["title"] == "a"


def test_if_match_current_applies(db_setup):
    t = client.post("/todos", json={"title": "a"}).json()
    r = client.patch(f"/todos/{t['todo_id']}", json={"title": "x"}, headers={"If-Match": "1"})
    assert r.status_code == 200 and r.json()["version"] == 2


def test_txn_replay_does_not_duplicate(db_setup):
    h = {"X-Txn-Id": "txn-1"}
    a = client.post("/todos", json={"title": "a"}, headers=h)
    b = client.post("/todos", json={"title": "a"}, headers=h)
    assert a.json() == b.json()
    assert len(client.get("/todos/root").json()) == 1


def test_txn_replays_409_consistently(db_setup):
    id = client.post("/todos", json={"title": "a"}).json()["todo_id"]
    client.patch(f"/todos/{id}", json={"done": True})
    h = {"If-Match": "1", "X-Txn-Id": "txn-2"}
    assert client.patch(f"/todos/{id}", json={"title": "x"}, headers=h).status_code == 409
    assert client.patch(f"/todos/{id}", json={"title": "x"}, headers=h).status_code == 409


def test_txn_replay_of_patch_applies_once(db_setup):
    id = client.post("/todos", json={"title": "a"}).json()["todo_id"]
    h = {"X-Txn-Id": "txn-3"}
    a = client.patch(f"/todos/{id}", json={"done": True}, headers=h)
    b = client.patch(f"/todos/{id}", json={"done": True}, headers=h)
    assert a.json() == b.json()
    assert client.get(f"/todos/{id}").json()["version"] == 2


def test_failed_request_is_not_logged(db_setup):
    missing = str(uuid.uuid4())
    h = {"X-Txn-Id": "txn-4"}
    assert client.patch(f"/todos/{missing}", json={"done": True}, headers=h).status_code == 404
    assert list(db.get_conn().collection("txn_log").stream()) == []


def test_split_returns_affected_parent_then_children(db_setup):
    id = client.post("/todos", json={"title": "p"}).json()["todo_id"]
    r = client.post(f"/todos/{id}/split", json={"descriptions": ["a", "b"]}).json()
    assert r["affected"][0]["todo_id"] == id
    assert r["version"] == 2 and r["affected"][0]["version"] == 2
    assert len(r["affected"]) == 3
    assert [a["todo_id"] for a in r["affected"][1:]] == r["child_ids"]
    assert all(a["version"] == 1 for a in r["affected"][1:])
    assert client.get(f"/todos/{id}").json()["version"] == 2


def test_undelete_returns_affected_subtree(db_setup):
    id = client.post("/todos", json={"title": "p"}).json()["todo_id"]
    client.post(f"/todos/{id}/split", json={"descriptions": ["a"]})
    client.delete(f"/todos/{id}")
    r = client.patch(f"/todos/{id}/undelete").json()
    assert [a["todo_id"] for a in r["affected"]] == [id]
    assert client.get(f"/todos/{id}").json()["version"] == r["version"]


def test_delete_stale_returns_409_and_delete_missing_is_204(db_setup):
    id = client.post("/todos", json={"title": "a"}).json()["todo_id"]
    client.patch(f"/todos/{id}", json={"done": True})
    assert client.delete(f"/todos/{id}", headers={"If-Match": "1"}).status_code == 409
    assert client.delete(f"/todos/{id}", headers={"If-Match": "2"}).status_code == 204
    assert client.delete(f"/todos/{id}").status_code == 204


def test_missing_txn_or_if_match_unchanged(db_setup):
    id = client.post("/todos", json={"title": "a"}).json()["todo_id"]
    assert client.patch(f"/todos/{id}", json={"done": True}).status_code == 200


def test_roots_come_back_in_creation_order(db_setup):
    ids = [client.post("/todos", json={"title": f"t{i}"}).json()["todo_id"] for i in range(5)]
    assert [t["todo_id"] for t in client.get("/todos/root").json()] == ids


def rev_of(response):
    return int(response.headers["x-rev"])


def test_rev_starts_at_0_and_bumps_once_per_write(db_setup):
    assert client.get("/todos/rev").json()["rev"] == 0
    a = client.post("/todos", json={"title": "a"})
    assert rev_of(a) == 1
    b = client.patch(f"/todos/{a.json()['todo_id']}", json={"done": True})
    assert rev_of(b) == 2
    assert client.get("/todos/rev").json()["rev"] == 2


def test_rev_does_not_move_for_conflicts_missing_or_reads(db_setup):
    id = client.post("/todos", json={"title": "a"}).json()["todo_id"]
    client.patch(f"/todos/{id}", json={"done": True})  # rev 2
    stale = client.patch(f"/todos/{id}", json={"title": "x"}, headers={"If-Match": "1"})
    assert stale.status_code == 409 and rev_of(stale) == 2
    gone = client.delete(f"/todos/{uuid.uuid4()}")
    assert gone.status_code == 204 and rev_of(gone) == 2
    missing = client.patch(f"/todos/{uuid.uuid4()}", json={"done": True})
    assert missing.status_code == 404
    client.get(f"/todos/{id}")
    assert client.get("/todos/rev").json()["rev"] == 2


def test_replayed_txn_returns_the_original_rev_and_does_not_bump(db_setup):
    h = {"X-Txn-Id": "rev-1"}
    a = client.post("/todos", json={"title": "a"}, headers=h)
    client.post("/todos", json={"title": "other"})  # rev 2
    b = client.post("/todos", json={"title": "a"}, headers=h)
    assert rev_of(a) == 1 and rev_of(b) == 1
    assert client.get("/todos/rev").json()["rev"] == 2


def test_tree_includes_current_rev(db_setup):
    client.post("/todos", json={"title": "a"})
    client.post("/todos", json={"title": "b"})
    assert client.get("/todos/tree").json()["rev"] == 2


def test_split_and_move_and_undelete_each_bump_rev_once(db_setup):
    id = client.post("/todos", json={"title": "p"}).json()["todo_id"]      # 1
    s = client.post(f"/todos/{id}/split", json={"descriptions": ["a", "b"]})  # 2
    assert rev_of(s) == 2
    kid = s.json()["child_ids"][0]
    assert rev_of(client.patch(f"/todos/{kid}/move/down")) == 3
    assert rev_of(client.delete(f"/todos/{id}")) == 4
    assert rev_of(client.patch(f"/todos/{id}/undelete")) == 5


def test_rev_prev_is_the_revision_the_request_started_from(db_setup):
    a = client.post("/todos", json={"title": "a"})
    assert (int(a.headers["x-rev-prev"]), rev_of(a)) == (0, 1)
    b = client.patch(f"/todos/{a.json()['todo_id']}", json={"done": True})
    assert (int(b.headers["x-rev-prev"]), rev_of(b)) == (1, 2)
    stale = client.patch(f"/todos/{a.json()['todo_id']}", json={"title": "x"}, headers={"If-Match": "1"})
    assert (int(stale.headers["x-rev-prev"]), rev_of(stale)) == (2, 2)


def test_replay_keeps_the_original_prev_and_rev(db_setup):
    h = {"X-Txn-Id": "rev-2"}
    a = client.post("/todos", json={"title": "a"}, headers=h)
    client.post("/todos", json={"title": "other"})
    b = client.post("/todos", json={"title": "a"}, headers=h)
    assert (b.headers["x-rev-prev"], b.headers["x-rev"]) == (a.headers["x-rev-prev"], a.headers["x-rev"])


def test_collapsed_defaults_false_and_persists(db_setup):
    t = client.post("/todos", json={"title": "a"}).json()
    assert t["collapsed"] is False
    r = client.patch(f"/todos/{t['todo_id']}", json={"collapsed": True})
    assert r.status_code == 200 and r.json()["collapsed"] is True
    assert client.get(f"/todos/{t['todo_id']}").json()["collapsed"] is True
    roots = client.get("/todos/tree").json()["roots"]
    assert roots[0]["collapsed"] is True


def test_collapsed_only_patch_skips_version_bump_and_check(db_setup):
    t = client.post("/todos", json={"title": "a"}).json()
    client.patch(f"/todos/{t['todo_id']}", json={"done": True})  # version -> 2
    # Stale If-Match does not conflict, and the version is untouched.
    r = client.patch(f"/todos/{t['todo_id']}", json={"collapsed": True}, headers={"If-Match": "1"})
    assert r.status_code == 200
    assert r.json()["version"] == 2 and r.json()["collapsed"] is True


def test_collapsed_with_other_fields_still_versioned(db_setup):
    t = client.post("/todos", json={"title": "a"}).json()
    r = client.patch(f"/todos/{t['todo_id']}", json={"collapsed": True, "done": True}, headers={"If-Match": "9"})
    assert r.status_code == 409
    r = client.patch(f"/todos/{t['todo_id']}", json={"collapsed": True, "done": True}, headers={"If-Match": "1"})
    assert r.json()["version"] == 2


def test_undelete_does_not_resurrect_children_deleted_earlier(db_setup):
    p = client.post("/todos", json={"title": "p"}).json()["todo_id"]
    client.post(f"/todos/{p}/split", json={"descriptions": ["a", "b"]})
    a, b = client.get(f"/todos/{p}").json()["child_ids"]
    client.delete(f"/todos/{a}")
    client.delete(f"/todos/{p}")
    client.patch(f"/todos/{p}/undelete")
    assert client.get(f"/todos/{p}").json()["child_ids"] == [b]
    assert client.get(f"/todos/{a}").status_code == 404


def test_tree_is_one_collection_read_and_matches_structure(db_setup, monkeypatch):
    p = client.post("/todos", json={"title": "p"}).json()["todo_id"]
    other = client.post("/todos", json={"title": "o"}).json()["todo_id"]
    client.post(f"/todos/{p}/split", json={"descriptions": ["a", "b"]})
    a, b = client.get(f"/todos/{p}").json()["child_ids"]
    client.post(f"/todos/{a}/split", json={"descriptions": ["a1"]})
    client.delete(f"/todos/{b}")
    dead = client.post("/todos", json={"title": "dead"}).json()["todo_id"]
    client.post(f"/todos/{dead}/split", json={"descriptions": ["orphan"]})
    client.delete(f"/todos/{dead}")

    calls = {"get_todo": 0}
    real = db.get_todo
    monkeypatch.setattr(db, "get_todo", lambda *a, **k: calls.__setitem__("get_todo", calls["get_todo"] + 1) or real(*a, **k))
    tree = client.get("/todos/tree").json()

    assert calls["get_todo"] == 0
    assert [r["todo_id"] for r in tree["roots"]] == [p, other]
    assert tree["todosById"][p]["child_ids"] == [a]
    assert len(tree["todosById"]) == 4  # p, other, a, a1 (b deleted, dead subtree hidden)


def test_collapsed_only_patch_bumps_rev(db_setup):
    # Collapse skips the version check but is a real write: bumping the rev is
    # what lets other windows notice it and refetch.
    t = client.post("/todos", json={"title": "a"}).json()
    before = client.get("/todos/rev").json()["rev"]
    r = client.patch(f"/todos/{t['todo_id']}", json={"collapsed": True})
    assert rev_of(r) == before + 1
    assert client.get("/todos/rev").json()["rev"] == before + 1


def test_roots_get_order_idx_and_can_be_moved(db_setup):
    ids = [client.post("/todos", json={"title": f"t{i}"}).json()["todo_id"] for i in range(3)]
    idx = [client.get(f"/todos/{i}").json()["order_idx"] for i in ids]
    assert idx == [0, 1, 2]
    r = client.patch(f"/todos/{ids[2]}/move/up")
    assert r.status_code == 200 and r.json()["order_idx"] == 1
    assert [t["todo_id"] for t in client.get("/todos/root").json()] == [ids[0], ids[2], ids[1]]
    assert client.patch(f"/todos/{ids[0]}/move/up").status_code == 400


def test_move_touches_only_the_two_swapped_siblings(db_setup):
    p = client.post("/todos", json={"title": "p"}).json()["todo_id"]
    client.post(f"/todos/{p}/split", json={"descriptions": ["a", "b", "c", "d"]})
    kids = client.get(f"/todos/{p}").json()["child_ids"]
    before = {k: client.get(f"/todos/{k}").json()["order_idx"] for k in kids}
    client.patch(f"/todos/{kids[1]}/move/down")
    after = {k: client.get(f"/todos/{k}").json()["order_idx"] for k in kids}
    assert after[kids[1]] == before[kids[2]] and after[kids[2]] == before[kids[1]]
    assert after[kids[0]] == before[kids[0]] and after[kids[3]] == before[kids[3]]


def test_move_compacts_legacy_roots_without_order_idx(db_setup):
    ids = [client.post("/todos", json={"title": f"t{i}"}).json()["todo_id"] for i in range(3)]
    for i in ids:
        db.get_conn().collection("todos").document(i).update({"order_idx": None})
    client.patch(f"/todos/{ids[2]}/move/up")
    assert [t["todo_id"] for t in client.get("/todos/root").json()] == [ids[0], ids[2], ids[1]]


def test_rev_endpoint_reports_app_version(db_setup):
    r = client.get("/todos/rev").json()
    assert "rev" in r
    # Same number the page ships with (APP_VERSION in web/app.js).
    import re
    shipped = re.search(r'APP_VERSION = "([^"]+)"', open("web/app.js").read()).group(1)
    assert r["version"] == shipped


def _mk(title, parent=None):
    t = client.post("/todos", json={"title": title}).json()["todo_id"]
    if parent is not None:
        client.patch(f"/todos/{t}/parent/{parent}", json={"parent_id": parent})
    return t


def _reparent(todo, parent, index=None, **kw):
    body = {"parent_id": parent}
    if index is not None:
        body["index"] = index
    return client.patch(f"/todos/{todo}/reparent", json=body, **kw)


def test_reparent_under_another_todo_appends_and_bumps_version(db_setup):
    a, b = _mk("a"), _mk("b")
    r = _reparent(b, a)
    assert r.status_code == 200
    assert r.json()["parent_id"] == a and r.json()["version"] == 2
    assert client.get(f"/todos/{a}").json()["child_ids"] == [b]
    assert [t["todo_id"] for t in client.get("/todos/root").json()] == [a]


def test_reparent_inserts_at_index_and_renumbers_siblings(db_setup):
    p = _mk("p")
    k1, k2, k3 = _mk("k1", p), _mk("k2", p), _mk("k3", p)
    x = _mk("x")
    assert _reparent(x, p, 1).status_code == 200
    assert client.get(f"/todos/{p}").json()["child_ids"] == [k1, x, k2, k3]
    idx = [client.get(f"/todos/{i}").json()["order_idx"] for i in (k1, x, k2, k3)]
    assert idx == sorted(idx) and len(set(idx)) == 4


def test_reparent_to_top_level_at_index(db_setup):
    a, b = _mk("a"), _mk("b")
    c = _mk("c", b)
    r = _reparent(c, None, 0)
    assert r.status_code == 200 and r.json()["parent_id"] is None
    assert [t["todo_id"] for t in client.get("/todos/root").json()] == [c, a, b]
    assert client.get(f"/todos/{b}").json()["child_ids"] == []


def test_reparent_within_same_parent_reorders(db_setup):
    p = _mk("p")
    k1, k2, k3 = _mk("k1", p), _mk("k2", p), _mk("k3", p)
    assert _reparent(k3, p, 0).status_code == 200
    assert client.get(f"/todos/{p}").json()["child_ids"] == [k3, k1, k2]


def test_reparent_into_own_subtree_is_rejected(db_setup):
    a = _mk("a")
    b = _mk("b", a)
    c = _mk("c", b)
    assert _reparent(a, c).status_code == 400
    assert _reparent(a, a).status_code == 400
    assert client.get(f"/todos/{a}").json()["parent_id"] is None


def test_reparent_to_missing_or_deleted_parent_is_404(db_setup):
    a, b = _mk("a"), _mk("b")
    assert _reparent(a, str(uuid.uuid4())).status_code == 404
    client.delete(f"/todos/{b}")
    assert _reparent(a, b).status_code == 404


def test_reparent_respects_if_match(db_setup):
    a, b = _mk("a"), _mk("b")
    assert _reparent(b, a, headers={"If-Match": "9"}).status_code == 409
    assert _reparent(b, a, headers={"If-Match": "1"}).status_code == 200


# ---- repeating todos ----------------------------------------------------

def _repeating(title="water plants", due="2026-09-14T09:00:00", unit="week", every=1):
    t = client.post("/todos", json={"title": title, "due_date": due}).json()["todo_id"]
    r = client.patch(f"/todos/{t}", json={"repeat": {"unit": unit, "every": every}})
    assert r.status_code == 200
    return t


def _spawn(todo, today="2026-09-14", **kw):
    return client.post(f"/todos/{todo}/repeat", json={"today": today}, **kw)


def test_repeat_rule_can_be_set_persisted_and_cleared(db_setup):
    t = _repeating(unit="week", every=2)
    assert client.get(f"/todos/{t}").json()["repeat"] == {"unit": "week", "every": 2}
    r = client.patch(f"/todos/{t}", json={"repeat": None})
    assert r.json()["repeat"] is None
    assert client.get(f"/todos/{t}").json()["repeat"] is None


def test_repeat_rule_rejects_unknown_units_and_bad_intervals(db_setup):
    t = client.post("/todos", json={"title": "a"}).json()["todo_id"]
    assert client.patch(f"/todos/{t}", json={"repeat": {"unit": "fortnight"}}).status_code == 422
    assert client.patch(f"/todos/{t}", json={"repeat": {"unit": "day", "every": 0}}).status_code == 422


def test_spawn_creates_the_next_open_occurrence_after_the_original(db_setup):
    t = _repeating(unit="week")
    other = client.post("/todos", json={"title": "other"}).json()["todo_id"]
    client.patch(f"/todos/{t}", json={"done": True})
    r = _spawn(t)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    copy = client.get(f"/todos/{body['spawned_id']}").json()
    assert copy["title"] == "water plants" and copy["done"] is False
    assert copy["due_date"] == "2026-09-21T09:00:00"
    assert copy["repeat"] == {"unit": "week", "every": 1}
    assert copy["spawned_id"] is None
    assert client.get(f"/todos/{t}").json()["spawned_id"] == body["spawned_id"]
    order = [x["todo_id"] for x in client.get("/todos/root").json()]
    assert order == [t, body["spawned_id"], other]


def test_spawn_uses_the_clients_today_to_skip_missed_occurrences(db_setup):
    t = _repeating(unit="day", due="2026-09-14T00:00:00")
    body = _spawn(t, today="2026-09-20").json()
    assert client.get(f"/todos/{body['spawned_id']}").json()["due_date"] == "2026-09-21T00:00:00"


def test_spawn_copies_the_live_subtree_reset_to_open_with_shifted_dates(db_setup):
    t = _repeating(unit="week", due="2026-09-14T00:00:00")
    k1 = _mk("k1", t)
    k2 = _mk("k2", t)
    gone = _mk("gone", t)
    g = _mk("g", k1)
    client.patch(f"/todos/{k1}", json={"done": True, "due_date": "2026-09-15T00:00:00"})
    client.patch(f"/todos/{g}", json={"done": True})
    client.delete(f"/todos/{gone}")

    body = _spawn(t).json()
    copy = client.get(f"/todos/{body['spawned_id']}").json()
    kids = [client.get(f"/todos/{c}").json() for c in copy["child_ids"]]
    assert [k["title"] for k in kids] == ["k1", "k2"]          # deleted one left out, order kept
    assert all(k["done"] is False for k in kids)
    assert kids[0]["due_date"] == "2026-09-22T00:00:00"        # shifted by the same 7 days
    assert kids[1]["due_date"] is None
    grand = client.get(f"/todos/{kids[0]['child_ids'][0]}").json()
    assert grand["title"] == "g" and grand["done"] is False
    assert kids[0]["todo_id"] != k1                             # new ids, originals untouched
    assert client.get(f"/todos/{k1}").json()["done"] is True


def test_a_todo_spawns_at_most_once(db_setup):
    t = _repeating()
    first = _spawn(t).json()
    again = _spawn(t).json()
    assert again["created"] is False and again["spawned_id"] == first["spawned_id"]
    assert len(client.get("/todos/root").json()) == 2


def test_spawn_retry_with_the_same_txn_id_replays_the_answer(db_setup):
    t = _repeating()
    a = _spawn(t, headers={"X-Txn-Id": "spawn-1"}).json()
    b = _spawn(t, headers={"X-Txn-Id": "spawn-1"}).json()
    assert a == b
    assert len(client.get("/todos/root").json()) == 2


def test_spawn_needs_a_repeat_rule_and_a_live_todo(db_setup):
    plain = client.post("/todos", json={"title": "a"}).json()["todo_id"]
    assert _spawn(plain).status_code == 400
    t = _repeating()
    client.delete(f"/todos/{t}")
    assert _spawn(t).status_code == 404
