"""Item types: registry, model, and every guard that reads a capability."""
import datetime as dt
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app import db, ics, models, push, tasks, tenant, types
from app.db_firestore_helpers import doc_to_todo, todo_to_doc
from app.main import app
from app.next_up import rank_next_up
from tests.helpers import TEST_USER, act_as, wipe_users

client = TestClient(app)


@pytest.fixture
def db_setup():
    act_as(app)
    db.init()
    wipe_users()
    token = tenant.set_user(TEST_USER)
    yield
    tenant.reset(token)
    db.teardown()


# ---- registry ---------------------------------------------------------------

def test_registry_has_the_three_types_and_flags():
    assert set(types.NAMES) == {"todo", "list", "project"}
    flags = {"hasCheckbox", "appearsInNextUp", "triggersAutodone", "countsInBadge", "showsProgress", "notifies"}
    for name in types.NAMES:
        assert flags <= set(types.caps(name))
        assert "title" in types.caps(name)["fields"]


def test_unknown_or_missing_type_falls_back_to_todo():
    assert types.caps(None) == types.caps("todo")
    assert types.caps("nonsense") == types.caps("todo")
    assert types.can_type("todo", "hasCheckbox") is True
    assert types.can_type("list", "hasCheckbox") is False
    assert types.can_type("project", "showsProgress") is True


# ---- model, storage, PATCH --------------------------------------------------

def test_model_literal_matches_registry():
    assert set(get_args(models.ItemType)) == set(types.NAMES)


def test_doc_round_trip_and_defaults():
    t = models.Todo(title="x", type="project")
    assert todo_to_doc(t)["type"] == "project"
    assert doc_to_todo(todo_to_doc(t)).type == "project"
    old = todo_to_doc(models.Todo(title="old"))
    del old["type"]
    assert doc_to_todo(old).type == "todo"          # documents from before types
    old["type"] = "from-the-future"
    assert doc_to_todo(old).type == "todo"          # unknown never breaks a read


def test_patch_type_keeps_other_fields(db_setup):
    r = client.post("/todos", json={"title": "a", "due_date": "2026-09-30T00:00:00"})
    tid, v = r.json()["todo_id"], r.json()["version"]
    assert r.json()["type"] == "todo"
    r = client.patch(f"/todos/{tid}", json={"type": "list"}, headers={"If-Match": str(v)})
    assert r.status_code == 200 and r.json()["type"] == "list"
    assert r.json()["due_date"] == "2026-09-30T00:00:00"      # kept, just inactive
    assert client.get(f"/todos/{tid}").json()["type"] == "list"
    assert client.patch(f"/todos/{tid}", json={"type": "bogus"}).status_code == 422


# ---- next up ----------------------------------------------------------------

_ALL: list[models.Todo] = []


def _mk(title, type="todo", due=None, done=False, kids=(), blocked_by=()):
    t = models.Todo(title=title, type=type, due_date=due, done=done, blocked_by=[b.todo_id for b in blocked_by])
    t.child_ids = [k.todo_id for k in kids]
    for i, k in enumerate(kids):
        k.parent_id, k.order_idx = t.todo_id, i
    _ALL.append(t)
    return t


def _rank(*roots):
    by_id = {str(t.todo_id): t for t in _ALL}
    return [i["title"] for i in rank_next_up(list(roots), by_id, 10)]


def test_containers_are_walked_through_but_never_listed():
    _ALL.clear()
    a, b = _mk("a"), _mk("b")
    proj = _mk("proj", "project", kids=[a, b])
    empty = _mk("empty list", "list")
    assert _rank(proj, empty) == ["a", "b"]


def test_container_done_is_ignored_and_dormant_due_does_not_inherit():
    _ALL.clear()
    a = _mk("a")
    lst = _mk("list", "list", due=dt.datetime(2026, 9, 1), done=True, kids=[a])
    other = _mk("other", due=dt.datetime(2026, 9, 10))
    assert _rank(lst, other) == ["other", "a"]      # a inherits no due from the list


def test_todo_holding_only_an_empty_container_is_a_leaf():
    _ALL.clear()
    inner = _mk("inner list", "list")
    parent = _mk("parent", kids=[inner])
    assert _rank(parent) == ["parent"]


def test_container_is_never_an_open_blocker():
    _ALL.clear()
    lst = _mk("list", "list")
    x = _mk("x", blocked_by=[lst])
    by_id = {str(t.todo_id): t for t in _ALL}
    assert rank_next_up([x], by_id, 10)[0]["blocked_by"] == []


# ---- push, heads-up, calendar -----------------------------------------------

def _due_today(title, type="todo"):
    return models.Todo(title=title, type=type, due_date=dt.datetime(2026, 9, 19, 12, 0))


def test_digest_skips_types_that_do_not_notify():
    now = dt.datetime(2026, 9, 19, 16, 0, tzinfo=dt.UTC)
    todos = [_due_today("real"), _due_today("hidden", "list"), _due_today("hidden2", "project")]
    out = push.plan_device("dev", "America/Los_Angeles", now, todos, lambda k: None)
    assert out[0].title == "1 due today" and out[0].body == "real"


def test_calendar_skips_types_that_do_not_notify():
    todos = {str(t.todo_id): t for t in [_due_today("real"), _due_today("hidden", "list")]}
    text = ics.build_calendar(todos)
    assert "SUMMARY:real" in text and "hidden" not in text


def test_heads_up_task_not_scheduled_for_containers():
    now = dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.UTC)
    due = dt.datetime(2026, 9, 19, 20, 0)                       # 13:00 in Los Angeles: timed, 6h out
    made = []
    create = lambda *a: made.append(a) or True  # noqa: E731
    assert tasks.schedule_heads_up("id1", due, False, False, now, "America/Los_Angeles", create) is True
    assert tasks.schedule_heads_up("id2", due, False, False, now, "America/Los_Angeles", create,
                                   item_type="list") is False
    assert len(made) == 1


def test_run_heads_up_stays_silent_for_a_todo_switched_to_a_list(db_setup):
    t = client.post("/todos", json={"title": "x", "due_date": "2026-09-19T20:00:00"}).json()
    client.patch(f"/todos/{t['todo_id']}", json={"type": "list"})
    got = push.run_heads_up(t["todo_id"], "2026-09-19T20:00:00", dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC),
                            send=lambda *a: None)
    assert got == {"sent": 0, "skipped": "stale"}


# ---- clear completed, blocked -----------------------------------------------

def _post(title, parent=None, done=False, type=None):
    tid = client.post("/todos", json={"title": title}).json()["todo_id"]
    body = {}
    if done:
        body["done"] = True
    if type:
        body["type"] = type
    if body:
        client.patch(f"/todos/{tid}", json=body)
    if parent:
        client.patch(f"/todos/{tid}/reparent", json={"parent_id": parent, "index": None})
    return tid


def test_clear_completed_derives_container_completion_from_its_todos(db_setup):
    proj = _post("proj", type="project")                  # done=False, but all its todos are done
    _post("t1", parent=proj, done=True)
    _post("t2", parent=proj, done=True)
    open_proj = _post("open proj", type="project")
    t3 = _post("t3", parent=open_proj, done=True)         # a done leaf is cleared even under an open parent
    _post("t4", parent=open_proj)
    empty = _post("empty", type="list", done=True)        # stale done, no todos: kept
    cleared = {x["todo_id"] for x in client.post("/todos/clear-completed").json()["cleared"]}
    assert cleared == {proj, t3}
    assert open_proj not in cleared and empty not in cleared


def test_container_does_not_block(db_setup):
    lst = _post("list", type="list")
    x = _post("x")
    client.patch(f"/todos/{x}", json={"blocked_by": [lst]})
    tree = client.get("/todos/tree").json()
    assert tree["todosById"][x]["blocked"] is False


# ---- generated client data --------------------------------------------------

def test_generated_client_data_is_current():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("gen_types", root / "scripts" / "gen_types.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (root / "web" / "types-data.js").read_text() == gen.render(), "run: python scripts/gen_types.py"


# ---- review fixes: dormant blocked_by on a container -------------------------

def test_container_dormant_blocked_by_blocks_nothing():
    _ALL.clear()
    blocker = _mk("blocker")
    child = _mk("child")
    lst = _mk("list", "list", kids=[child], blocked_by=[blocker])   # blocked_by is dormant on a list
    other = _mk("other", blocked_by=[blocker])
    by_id = {str(t.todo_id): t for t in _ALL}
    got = {i["title"]: i["blocked_by"] for i in rank_next_up([lst, blocker, other], by_id, 10)}
    assert got["child"] == []                      # not held back by its list's dormant blocker
    assert got["other"] == ["blocker"]             # a real todo still is


def test_container_with_dormant_blocked_by_is_not_flagged_blocked(db_setup):
    blocker = _post("blocker")
    lst = _post("list", type="list")
    client.patch(f"/todos/{lst}", json={"blocked_by": [blocker]})
    tree = client.get("/todos/tree").json()
    assert tree["todosById"][lst]["blocked"] is False


# ---- type on create and split ------------------------------------------------

def test_registry_documents_every_type():
    for name in types.NAMES:
        spec = types.caps(name)
        assert spec["description"] and spec["icon"]
        assert spec["defaultChildType"] in types.NAMES


def test_create_accepts_type_and_defaults_to_todo(db_setup):
    assert client.post("/todos", json={"title": "plain"}).json()["type"] == "todo"
    made = client.post("/todos", json={"title": "big", "type": "project"}).json()
    assert made["type"] == "project"
    assert client.post("/todos", json={"title": "x", "type": "nonsense"}).status_code == 422


def test_create_drops_a_due_date_the_type_cannot_have(db_setup):
    made = client.post("/todos", json={"title": "l", "type": "list", "due_date": "2026-10-01T00:00:00"}).json()
    assert made["due_date"] is None
    todo = client.post("/todos", json={"title": "t", "due_date": "2026-10-01T00:00:00"}).json()
    assert todo["due_date"] is not None


def test_split_applies_type_to_every_child(db_setup):
    parent = client.post("/todos", json={"title": "p", "type": "project"}).json()
    res = client.post(f"/todos/{parent['todo_id']}/split", json={"descriptions": ["a", "b"], "type": "list"})
    assert res.status_code == 200
    by_id = client.get("/todos/tree").json()["todosById"]
    kids = [by_id[i] for i in by_id[parent["todo_id"]]["child_ids"]]
    assert [k["type"] for k in kids] == ["list", "list"]
    plain = client.post(f"/todos/{parent['todo_id']}/split", json={"descriptions": ["c"]})
    assert plain.status_code == 200


def test_split_rejects_unknown_type(db_setup):
    parent = client.post("/todos", json={"title": "p"}).json()
    res = client.post(f"/todos/{parent['todo_id']}/split", json={"descriptions": ["a"], "type": "nonsense"})
    assert res.status_code == 422
