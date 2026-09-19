"""Ranking rules for the Next up view (app/next_up.py) and its endpoint."""
import datetime

from fastapi.testclient import TestClient

from app import db, models
from app.main import app
from app.next_up import rank_next_up


def d(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 9, day)


_ALL: dict[str, models.Todo] = {}


def mk(title, due=None, done=False, order=None, kids=()):
    t = models.Todo(title=title, due_date=due, done=done, order_idx=order)
    t.child_ids = [k.todo_id for k in kids]
    for k in kids:
        k.parent_id = t.todo_id
    _ALL[str(t.todo_id)] = t
    return t


def rank(*roots, limit=10):
    return rank_next_up(list(roots), _ALL, limit)


def titles(items):
    return [i["title"] for i in items]


def test_earlier_due_first_then_undated_in_list_order():
    a, b, c, e = mk("later", d(20)), mk("undated 1"), mk("sooner", d(10)), mk("undated 2")
    assert titles(rank(a, b, c, e)) == ["sooner", "later", "undated 1", "undated 2"]


def test_subtasks_inherit_parent_due_date():
    parent = mk("trip", d(25), kids=[mk("flights", order=0), mk("hotel", order=1)])
    soon = mk("soon", d(20))
    out = rank(parent, soon)
    assert titles(out) == ["soon", "flights", "hotel"]
    assert out[1]["due_source"] == "parent"
    assert out[1]["effective_due"] == d(25)
    assert out[1]["path"] == ["trip"]


def test_own_earlier_date_beats_parent_date():
    parent = mk("trip", d(25), kids=[mk("plain", order=0), mk("urgent", d(12), order=1)])
    out = rank(parent)
    assert titles(out) == ["urgent", "plain"]
    assert out[0]["due_source"] == "self"


def test_parent_is_skipped_while_it_has_open_children_but_counts_when_finished():
    parent = mk("p", d(20), kids=[mk("open child", order=0), mk("done child", done=True, order=1)])
    assert titles(rank(parent)) == ["open child"]
    finished = mk("q", d(20), kids=[mk("all done", done=True)])
    assert titles(rank(finished)) == ["q"]


def test_done_roots_and_their_subtrees_are_left_out():
    assert rank(mk("x", done=True, kids=[mk("y")])) == []


def test_children_follow_order_idx_and_limit_applies():
    parent = mk("p", kids=[mk("second", order=1), mk("first", order=0)])
    assert titles(rank(parent)) == ["first", "second"]
    many = [mk(f"t{i}", d(1 + i)) for i in range(15)]
    out = rank(*many, limit=10)
    assert len(out) == 10 and out[0]["rank"] == 1 and out[-1]["rank"] == 10


def test_endpoint_returns_ranked_items():
    client = TestClient(app)
    db.init()
    for name in ("todos", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    client.post("/todos", json={"title": "undated"})
    client.post("/todos", json={"title": "due", "due_date": "2026-09-10"})
    response = client.get("/todos/next")
    assert response.status_code == 200
    assert [i["title"] for i in response.json()["items"]] == ["due", "undated"]
    assert client.get("/todos/next?limit=1").json()["items"][0]["title"] == "due"
    db.teardown()
