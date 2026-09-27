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
    assert set(types.NAMES) == {"todo", "list", "project", "note", "calendar", "calendar_event", "mount"}
    flags = {"hasCheckbox", "appearsInNextUp", "triggersAutodone", "countsInBadge", "showsProgress", "notifies",
             "allowsUserChildren", "editable", "userCreatable", "shareable"}
    for name in types.NAMES:
        assert flags <= set(types.caps(name))
        assert "title" in types.caps(name)["fields"]


def test_registry_has_calendar_types_and_new_flags():
    assert {"calendar", "calendar_event"} <= set(types.NAMES)
    for name in types.NAMES:
        assert "allowsUserChildren" in types.caps(name)
        assert "editable" in types.caps(name)
    assert types.can_type("todo", "allowsUserChildren") is True
    assert types.can_type("calendar", "allowsUserChildren") is False
    assert types.can_type("calendar_event", "allowsUserChildren") is False
    assert types.can_type("calendar_event", "editable") is False
    assert types.can_type("calendar", "editable") is True
    assert types.has_field_type("calendar", "calendar_url")
    assert types.has_field_type("calendar_event", "location")
    assert types.has_field_type("calendar_event", "due_date")
    assert types.can_type("calendar_event", "hasCheckbox") is False
    assert types.can_type("calendar_event", "appearsInNextUp") is True
    assert types.can_type("calendar_event", "notifies") is True
    assert types.can_type("calendar", "appearsInNextUp") is False
    # No attachments (images) on calendar items: the user doesn't need to add
    # images to a calendar feed.
    assert types.caps("calendar")["fields"] == ["title", "calendar_url", "color"]
    assert not types.has_field_type("calendar", "attachments")


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


def test_split_rejected_under_calendar(db_setup):
    parent = models.Todo(title="Family calendar", type="calendar")
    db.create_todo(parent)
    resp = client.post(f"/todos/{parent.todo_id}/split", json={"descriptions": ["x"]},
                       headers={"Authorization": "Bearer test", "X-Txn-Id": "t1"})
    assert resp.status_code == 400
    assert "does not accept" in resp.json()["detail"]


def test_reparent_rejected_under_calendar(db_setup):
    parent = models.Todo(title="Family calendar", type="calendar")
    db.create_todo(parent)
    child = models.Todo(title="a todo")
    db.create_todo(child)
    resp = client.patch(f"/todos/{child.todo_id}/reparent", json={"parent_id": str(parent.todo_id)},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400
    assert "does not accept" in resp.json()["detail"]


def test_reparent_to_top_level_still_allowed(db_setup):
    """Sanity: the guard only fires for a real parent_id, not parent_id: null."""
    child = models.Todo(title="a todo", parent_id=None)
    db.create_todo(child)
    resp = client.patch(f"/todos/{child.todo_id}/reparent", json={"parent_id": None},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200


# ---- editable: false enforced server-side (Task 12) --------------------------

def test_patch_rejected_on_uneditable_type(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    event = models.Todo(title="Standup", type="calendar_event", parent_id=cal.todo_id, external_uid="x@y")
    db.create_todo(event)
    resp = client.patch(f"/todos/{event.todo_id}", json={"title": "Hacked"},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400
    assert "not editable" in resp.json()["detail"]


def test_patch_type_change_away_from_uneditable_rejected(db_setup):
    """The specific orphaning exploit Task 11's review found: a raw PATCH changing
    `type` away from calendar_event must be rejected same as any other field edit,
    not just the fields a naive guard might have special-cased."""
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    event = models.Todo(title="Standup", type="calendar_event", parent_id=cal.todo_id, external_uid="x@y")
    db.create_todo(event)
    resp = client.patch(f"/todos/{event.todo_id}", json={"type": "todo"},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400


def test_delete_rejected_on_uneditable_type(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    event = models.Todo(title="Standup", type="calendar_event", parent_id=cal.todo_id, external_uid="x@y")
    db.create_todo(event)
    resp = client.delete(f"/todos/{event.todo_id}", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400


def test_patch_still_allowed_on_editable_calendar_item(db_setup):
    """Sanity: the guard only fires for editable: false, not for `calendar` itself
    (editable: true — you can still rename it, change its color, edit its URL)."""
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    resp = client.patch(f"/todos/{cal.todo_id}", json={"title": "Renamed"},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200


def test_missing_or_unknown_priority_reads_as_normal():
    doc = {"todo_id": "11111111-1111-1111-1111-111111111111", "title": "x",
           "create_date": "2026-09-23T00:00:00"}
    assert doc_to_todo(doc).priority == "normal"
    assert doc_to_todo({**doc, "priority": "nope"}).priority == "normal"
    stored = todo_to_doc(models.Todo(title="x", priority="high"))
    assert stored["priority"] == "high"


def test_priority_patch_on_calendar_event_bumps_version(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    event = models.Todo(title="Standup", type="calendar_event", parent_id=cal.todo_id, external_uid="x@y")
    db.create_todo(event)
    headers = {"Authorization": "Bearer test", "If-Match": "1"}
    resp = client.patch(f"/todos/{event.todo_id}", json={"priority": "low"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["priority"] == "low" and body["version"] == 2
    stale = client.patch(f"/todos/{event.todo_id}", json={"priority": "high"}, headers=headers)
    assert stale.status_code == 409
    assert client.patch(f"/todos/{event.todo_id}", json={"title": "Hacked"},
                        headers={"Authorization": "Bearer test", "If-Match": "2"}).status_code == 400
    assert client.patch(f"/todos/{event.todo_id}", json={"priority": "high", "title": "Hacked"},
                        headers={"Authorization": "Bearer test", "If-Match": "2"}).status_code == 400
    assert client.patch(f"/todos/{event.todo_id}", json={"priority": "urgent"},
                        headers={"Authorization": "Bearer test", "If-Match": "2"}).status_code == 422


def test_collapsed_only_patch_still_allowed_on_uneditable_type(db_setup):
    """Collapse is view state (per sync-model.md), not content — it must NOT be
    blocked by the editable guard, or the client can't fold/unfold a calendar_event
    row (collapsing view state is harmless even on a read-only item)."""
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    event = models.Todo(title="Standup", type="calendar_event", parent_id=cal.todo_id, external_uid="x@y")
    db.create_todo(event)
    resp = client.patch(f"/todos/{event.todo_id}", json={"collapsed": True},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200


def test_reparent_rejected_for_uneditable_item(db_setup):
    """A calendar_event can't be dragged out of its calendar and orphaned (C3)."""
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    other = models.Todo(title="Other")
    db.create_todo(other)
    event = models.Todo(title="Standup", type="calendar_event", parent_id=cal.todo_id, external_uid="x@y")
    db.create_todo(event)
    resp = client.patch(f"/todos/{event.todo_id}/reparent", json={"parent_id": str(other.todo_id)},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400
    assert "not editable" in resp.json()["detail"]


def test_move_rejected_for_uneditable_item(db_setup):
    """A calendar_event can't be reordered within its calendar either (C3)."""
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    event = models.Todo(title="Standup", type="calendar_event", parent_id=cal.todo_id, external_uid="x@y")
    db.create_todo(event)
    resp = client.patch(f"/todos/{event.todo_id}/move/down",
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400
    assert "not editable" in resp.json()["detail"]


def test_note_is_a_text_item_that_can_hold_children():
    assert "note" in types.NAMES
    assert types.caps("note")["fields"] == ["title", "content", "color", "links", "attachments"]
    assert types.caps("note")["defaultChildType"] == "note"
    for flag in ("hasCheckbox", "appearsInNextUp", "triggersAutodone", "countsInBadge",
                 "showsProgress", "notifies"):
        assert types.can_type("note", flag) is False
    assert types.can_type("note", "allowsUserChildren") is True
    assert types.can_type("note", "editable") is True


def test_note_content_is_stored_capped_and_kept_when_the_type_changes(db_setup):
    parent = client.post("/todos", json={"title": "p", "type": "list"}).json()
    made = client.post(f"/todos/{parent['todo_id']}/split", json={
        "descriptions": ["Meeting"], "type": "note", "content": "Hello **world**",
    })
    assert made.status_code == 200
    child_id = made.json()["affected"][1]["todo_id"]
    got = client.get(f"/todos/{child_id}").json()
    assert got["type"] == "note"
    assert got["content"] == "Hello **world**"

    several = client.post(f"/todos/{parent['todo_id']}/split", json={
        "descriptions": ["one", "two"], "type": "note", "content": "should not copy",
    })
    assert several.status_code == 200
    by_id = client.get("/todos/tree").json()["todosById"]
    kids = [by_id[i] for i in by_id if by_id[i].get("title") in ("one", "two")]
    assert kids and all(k["content"] in (None, "") for k in kids)

    patched = client.patch(f"/todos/{child_id}", json={"content": "updated"},
                           headers={"If-Match": str(got["version"])})
    assert patched.status_code == 200 and patched.json()["content"] == "updated"
    cleared = client.patch(f"/todos/{child_id}", json={"content": ""},
                           headers={"If-Match": str(patched.json()["version"])})
    assert cleared.status_code == 200 and cleared.json()["content"] in (None, "")
    too_long = client.patch(f"/todos/{child_id}", json={"content": "x" * 100_001},
                            headers={"If-Match": str(cleared.json()["version"])})
    assert too_long.status_code == 422
    kept = client.patch(f"/todos/{child_id}", json={"content": "still here", "type": "list"},
                        headers={"If-Match": str(cleared.json()["version"])})
    assert kept.status_code == 200
    assert kept.json()["type"] == "list" and kept.json()["content"] == "still here"
    old = todo_to_doc(models.Todo(title="old"))
    old.pop("content", None)
    assert doc_to_todo(old).content is None


# ---- mount (sharing) -----------------------------------------------------------

def test_only_plain_types_are_shareable():
    assert {n for n in types.NAMES if types.can_type(n, "shareable")} == {"todo", "list", "project", "note"}


def test_mount_is_not_user_creatable():
    assert types.can_type("mount", "userCreatable") is False
    assert set(types.USER_NAMES) == set(types.NAMES) - {"mount"}
    assert set(get_args(models.UserItemType)) == set(types.USER_NAMES)


def test_mount_is_refused_on_create_patch_and_split(db_setup):
    assert client.post("/todos", json={"title": "x", "type": "mount"}).status_code == 422
    made = client.post("/todos", json={"title": "x"}).json()["todo_id"]
    assert client.patch(f"/todos/{made}", json={"type": "mount"}).status_code == 422
    assert client.post(f"/todos/{made}/split", json={"descriptions": ["a"], "type": "mount"}).status_code == 422


def test_last_edited_by_round_trips_and_share_tags_are_never_stored():
    t = models.Todo(title="x", last_edited_by="kid@example.com",
                    share=models.ShareTag(id="s", mode="rw", owner="me@example.com"), share_root=True)
    doc = todo_to_doc(t)
    assert doc["last_edited_by"] == "kid@example.com"
    assert "share" not in doc and "share_root" not in doc
    assert doc_to_todo(doc).last_edited_by == "kid@example.com"
