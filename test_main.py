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
    assert id in {a["todo_id"] for a in r["affected"]}
    assert len(r["affected"]) == 2
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
    assert client.get("/todos/rev").json() == {"rev": 0}
    a = client.post("/todos", json={"title": "a"})
    assert rev_of(a) == 1
    b = client.patch(f"/todos/{a.json()['todo_id']}", json={"done": True})
    assert rev_of(b) == 2
    assert client.get("/todos/rev").json() == {"rev": 2}


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
    assert client.get("/todos/rev").json() == {"rev": 2}


def test_replayed_txn_returns_the_original_rev_and_does_not_bump(db_setup):
    h = {"X-Txn-Id": "rev-1"}
    a = client.post("/todos", json={"title": "a"}, headers=h)
    client.post("/todos", json={"title": "other"})  # rev 2
    b = client.post("/todos", json={"title": "a"}, headers=h)
    assert rev_of(a) == 1 and rev_of(b) == 1
    assert client.get("/todos/rev").json() == {"rev": 2}


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
