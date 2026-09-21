# Item types — Slice 1 (registry, data model, capability guards) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every todo carries a `type` (`todo` | `list` | `project`), a shared registry declares what each type can do, and every server and client feature that cares (Next Up, push, heads-ups, ICS, clear-completed, blocked, badge, autodone) asks the registry instead of hard-coding.

**Architecture:** `app/types.json` is the single source of truth. Python loads it (`app/types.py`); `scripts/gen_types.py` generates a checked-in `web/types-data.js` from it, wrapped by `web/types.js`. A test fails when the generated file is stale. Type switching is an ordinary `PATCH /todos/{id}` content edit that changes only `type`; a container's own `done` is ignored everywhere.

**Tech Stack:** FastAPI/pydantic, Firestore (emulator via `scripts/test.sh`), vanilla JS UMD modules tested with `node --test`.

**Spec:** `docs/superpowers/specs/2026-09-21-item-types-design.md`

## Global Constraints

- Types: `todo`, `list`, `project`. Missing or unknown `type` reads as `todo` (server and client).
- Capability flags: `hasCheckbox`, `appearsInNextUp`, `triggersAutodone`, `countsInBadge`, `showsProgress`, `notifies`. No `if type === "todo"` in feature code.
- Switching type patches only `type`; `due_date`, `repeat`, `done` are never touched.
- A container's (`hasCheckbox: false`) own `done` is ignored everywhere.
- New docs write `type: "todo"` explicitly; no migration.
- Python: ruff line length 120, mypy over `app`. Run Python tests only via `scripts/test.sh` (emulator); JS via `node --test tests_js/*.test.js`.
- Same commit as any behaviour change: update `docs/okf/` files, bump their `timestamp`, append to `docs/okf/log.md` (project CLAUDE.md).
- Commit trailer: `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Deviation from spec, deliberate: `types.json` carries all three types in slice 1 (data only) because guards can't be tested otherwise. Row/edit-sheet renderers, the `hasCheckbox` row change, the done-sink change and both pickers are slice 2 (unreachable from the UI until then).

## File Structure

- Create `app/types.json` — the registry data.
- Create `app/types.py` — `NAMES`, `caps(name)`, `can(item, flag)`, `can_type(name, flag)`, `has_field(item, field)`.
- Create `scripts/gen_types.py` — writes `web/types-data.js`; `render()` returns the text.
- Create `web/types-data.js` — generated, checked in.
- Create `web/types.js` — `Types.get/can/hasField/names`.
- Modify `app/models.py`, `app/db_firestore_helpers.py`, `app/routes/todos.py` — the field and PATCH.
- Modify `app/next_up.py`, `app/push.py`, `app/tasks.py`, `app/ics.py`, `app/db_firestore.py` — guards.
- Modify `web/sync.js`, `web/autodone.js`, `web/badge.js`, `web/index.html` — client.
- Tests: `tests/test_item_types.py` (new), `tests_js/types.test.js` (new), additions to `tests_js/autodone.test.js`, `badge.test.js`, `sync.test.js`.

---

### Task 1: Registry and Python loader

**Files:** Create `app/types.json`, `app/types.py`, `tests/test_item_types.py`.

**Produces:** `types.NAMES: tuple[str, ...]`; `types.caps(name: str | None) -> dict`; `types.can(item, flag: str) -> bool` (item has `.type`); `types.can_type(name: str | None, flag: str) -> bool`; `types.has_field(item, field: str) -> bool`.

- [ ] **Step 1: Write the failing test** (`tests/test_item_types.py`)

```python
"""Item types: registry, model, and every guard that reads a capability."""
from app import types


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
```

- [ ] **Step 2: Run it, expect failure**

Run: `scripts/test.sh tests/test_item_types.py -q` — Expected: ImportError (`app.types` missing).

- [ ] **Step 3: Create `app/types.json`**

```json
{
  "todo": {
    "fields": ["title", "due_date", "repeat", "color", "links", "blocked_by", "references"],
    "hasCheckbox": true,
    "appearsInNextUp": true,
    "triggersAutodone": true,
    "countsInBadge": true,
    "showsProgress": false,
    "notifies": true
  },
  "list": {
    "fields": ["title", "color", "links", "references"],
    "hasCheckbox": false,
    "appearsInNextUp": false,
    "triggersAutodone": false,
    "countsInBadge": false,
    "showsProgress": false,
    "notifies": false
  },
  "project": {
    "fields": ["title", "color", "links", "references"],
    "hasCheckbox": false,
    "appearsInNextUp": false,
    "triggersAutodone": false,
    "countsInBadge": false,
    "showsProgress": true,
    "notifies": false
  }
}
```

- [ ] **Step 4: Create `app/types.py`**

```python
"""Item types: what each type can do, read from app/types.json.

The same JSON generates web/types-data.js (scripts/gen_types.py), so the server
and the client can never disagree. Feature code asks `can(item, flag)`; it never
compares a type name. A missing or unknown type behaves as "todo".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SPEC: dict[str, dict[str, Any]] = json.loads(Path(__file__).with_name("types.json").read_text())
DEFAULT = "todo"
NAMES = tuple(_SPEC)


def caps(name: str | None) -> dict[str, Any]:
    return _SPEC.get(name or DEFAULT, _SPEC[DEFAULT])


def can_type(name: str | None, flag: str) -> bool:
    return bool(caps(name)[flag])


def can(item: Any, flag: str) -> bool:
    return can_type(getattr(item, "type", DEFAULT), flag)


def has_field(item: Any, field: str) -> bool:
    return field in caps(getattr(item, "type", DEFAULT))["fields"]
```

- [ ] **Step 5: Run, expect pass.** `scripts/test.sh tests/test_item_types.py -q`
- [ ] **Step 6: Commit** — `git add app/types.json app/types.py tests/test_item_types.py && git commit -m "Add the item type registry and its Python loader"` (+ trailer)

---

### Task 2: `Todo.type` in the model, storage and PATCH

**Files:** Modify `app/models.py`, `app/db_firestore_helpers.py`, `app/routes/todos.py`; test in `tests/test_item_types.py`.

**Consumes:** `types.NAMES`, `types.DEFAULT`. **Produces:** `models.ItemType`, `Todo.type`, `TodoUpdate.type`.

- [ ] **Step 1: Failing tests** (append to `tests/test_item_types.py`)

```python
import pytest
from fastapi.testclient import TestClient

from app import db, models
from app.main import app
from app.db_firestore_helpers import doc_to_todo, todo_to_doc

client = TestClient(app)


@pytest.fixture
def db_setup():
    db.init()
    for name in ("todos", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield
    db.teardown()


def test_model_literal_matches_registry():
    from typing import get_args
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
    r = client.patch(f"/todos/{tid}", json={"type": "bogus"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run, expect failures** (`AttributeError: ItemType`, etc.)
- [ ] **Step 3: `app/models.py`** — after `Color = ...`/`COLORS` add `ItemType = Literal["todo", "list", "project"]`; add to `TodoUpdate`: `type: ItemType | None = Field(None)`; add to `Todo` (after `color`): `type: ItemType = Field("todo")`.
- [ ] **Step 4: `app/db_firestore_helpers.py`** — import `from app import models, types`; in `doc_to_todo` add `type=doc_dict.get("type") if doc_dict.get("type") in types.NAMES else types.DEFAULT,`; in `todo_to_doc` add `"type": todo.type,`.
- [ ] **Step 5: `app/routes/todos.py`** — in `update_todo`'s `action`, after the `color` block add:

```python
        if body.type is not None:
            todo.type = body.type  # only the label changes; due_date, repeat and done stay as they are
```

- [ ] **Step 6: Run** `scripts/test.sh tests/test_item_types.py -q` — pass; also `scripts/test.sh -q` for regressions (old tests build docs without `type`).
- [ ] **Step 7: Commit** — "Give every todo a type (default todo) and let PATCH change it".

---

### Task 3: Next Up follows capabilities

**Files:** Modify `app/next_up.py`; tests in `tests/test_item_types.py`.

**Consumes:** `types.can`, `types.has_field`. Rules: containers are walked through but never emitted; a container's `done` and dormant `due_date` are ignored; a todo whose only open descendants are empty containers is itself a leaf; containers are never open blockers.

- [ ] **Step 1: Failing tests** (append; reuses the `mk` idea locally)

```python
import datetime

from app.next_up import rank_next_up


def _mk(title, type="todo", due=None, done=False, kids=(), blocked_by=()):
    t = models.Todo(title=title, type=type, due_date=due, done=done, blocked_by=[b.todo_id for b in blocked_by])
    t.child_ids = [k.todo_id for k in kids]
    for i, k in enumerate(kids):
        k.parent_id, k.order_idx = t.todo_id, i
    return t


def _rank(*roots):
    by_id = {str(t.todo_id): t for t in _ALL}
    return [i["title"] for i in rank_next_up(list(roots), by_id, 10)]


_ALL: list[models.Todo] = []


def _tree(t):
    _ALL.append(t)
    return t


def test_containers_are_walked_through_but_never_listed():
    _ALL.clear()
    a, b = _tree(_mk("a")), _tree(_mk("b"))
    proj = _tree(_mk("proj", "project", kids=[a, b]))
    empty = _tree(_mk("empty list", "list"))
    assert _rank(proj, empty) == ["a", "b"]


def test_container_done_is_ignored_and_dormant_due_does_not_inherit():
    _ALL.clear()
    a = _tree(_mk("a"))
    lst = _tree(_mk("list", "list", due=datetime.datetime(2026, 9, 1), done=True, kids=[a]))
    other = _tree(_mk("other", due=datetime.datetime(2026, 9, 10)))
    assert _rank(lst, other) == ["other", "a"]      # a inherits no due from the list


def test_todo_holding_only_an_empty_container_is_a_leaf():
    _ALL.clear()
    inner = _tree(_mk("inner list", "list"))
    parent = _tree(_mk("parent", kids=[inner]))
    assert _rank(parent) == ["parent"]


def test_container_is_never_an_open_blocker():
    _ALL.clear()
    lst = _tree(_mk("list", "list"))
    x = _tree(_mk("x", blocked_by=[lst]))
    by_id = {str(t.todo_id): t for t in _ALL}
    assert rank_next_up([x], by_id, 10)[0]["blocked_by"] == []
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Edit `app/next_up.py`** — `from app import models, types`. Replace the three open-checks and `walk`:

```python
def _open(todo: models.Todo) -> bool:
    """Still to be walked: live, and (for a type with a done state) not done. A container's
    own `done` means nothing, so its todos beneath it stay reachable."""
    return not todo.deleted and (not todo.done or not types.can(todo, "hasCheckbox"))
```

In `rank_next_up`: `open_children` filter becomes `kids = [k for k in kids if _open(k)]`. Replace `walk` with:

```python
    def walk(todo, index_path, titles, inherited) -> bool:
        """Emits the candidates at or beneath `todo`; True when it emitted any."""
        own = _due(todo) if types.has_field(todo, "due_date") else None
        best = inherited
        if own is not None and (best is None or own < best[0]):
            best = (own, todo)
        emitted = False
        for i, kid in enumerate(open_children(todo)):
            emitted = walk(kid, index_path + (i,), titles + [todo.title], best) or emitted
        if emitted or not types.can(todo, "appearsInNextUp"):
            return emitted
        source = best[1] if best else None
        candidates.append((
            best[0] if best else _NO_DATE, own or _NO_DATE, index_path, todo, titles,
            source.due_date if source else None,
            "self" if source is todo else ("parent" if source else None),
        ))
        return True
```

Root loop: `if _open(root): walk(root, (i,), [], None)`. In `open_blockers`: `if b is not None and _open(b) and types.can(b, "hasCheckbox"):`.

- [ ] **Step 4: Run** `scripts/test.sh tests/test_item_types.py tests/test_next_up.py -q` — all pass.
- [ ] **Step 5: Commit** — "Next Up asks the type registry: containers are walked, not listed".

---

### Task 4: Push, heads-up and calendar follow `notifies`

**Files:** Modify `app/push.py`, `app/tasks.py`, `app/ics.py`; tests in `tests/test_item_types.py`.

- [ ] **Step 1: Failing tests**

```python
import datetime as dt

from app import ics, push, tasks


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
    create = lambda *a: made.append(a) or True
    assert tasks.schedule_heads_up("id1", due, False, False, now, "America/Los_Angeles", create) is True
    assert tasks.schedule_heads_up("id2", due, False, False, now, "America/Los_Angeles", create,
                                   item_type="list") is False
    assert len(made) == 1


def test_run_heads_up_stays_silent_for_a_todo_switched_to_a_list(db_setup):
    t = client.post("/todos", json={"title": "x", "due_date": "2026-09-19T20:00:00"}).json()
    client.patch(f"/todos/{t['todo_id']}", json={"type": "list"})
    got = push.run_heads_up(t["todo_id"], "2026-09-19T20:00:00", dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC),
                            send=lambda *a: None)
    assert got["sent"] == 0
```

(Adjust the `Push` attribute names to the real dataclass fields — `Push(key, title, body, todo_ids, silent)` — when writing; check `app/push.py` for the exact names.)

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: `app/push.py`** — `from app import models, types`. In `plan_device`, add `and types.can(t, "notifies")` after `not t.done and not t.deleted`. In `run_heads_up`, change the stale test to `todo is None or todo.done or not types.can(todo, "notifies") or todo.due_date is None or ...`. In `run_notify`, pass the type through: `tasks.schedule_heads_up(str(t.todo_id), t.due_date, t.done, t.deleted, now_utc, tz, create_task, item_type=t.type)`.
- [ ] **Step 4: `app/tasks.py`** — `from app import push, types`. `schedule_heads_up(..., create=None, item_type: str = "todo")`; first line becomes `if done or deleted or due is None or not types.can_type(item_type, "notifies"): return False`. In `schedule_from_body` pass `item_type=body.get("type", "todo")`.
- [ ] **Step 5: `app/ics.py`** — `from app import models, types`; in `build_calendar` add `and types.can(t, "notifies")` to the `open_dated` filter.
- [ ] **Step 6: Run** `scripts/test.sh tests/test_item_types.py tests/test_push_logic.py tests/test_push_api.py tests/test_tasks.py tests/test_calendar.py -q` — pass.
- [ ] **Step 7: Commit** — "Push, heads-ups and the calendar feed follow the notifies capability".

---

### Task 5: Clear completed and `blocked` (server)

**Files:** Modify `app/db_firestore.py` (`clear_completed` ~328–365, `get_tree` blocked ~574); tests in `tests/test_item_types.py`.

Rule: a container is "all done" when everything beneath it is; it is cleared only if it also holds at least one todo. Its own `done` is ignored. A container is never a blocker.

- [ ] **Step 1: Failing tests**

```python
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
    _post("t3", parent=open_proj, done=True)
    _post("t4", parent=open_proj)
    empty = _post("empty", type="list", done=True)        # stale done, no todos: kept
    cleared = {x["todo_id"] for x in client.post("/todos/clear-completed").json()["cleared"]}
    assert cleared == {proj}
    assert empty not in cleared


def test_container_does_not_block(db_setup):
    lst = _post("list", type="list")
    x = _post("x")
    client.patch(f"/todos/{x}", json={"blocked_by": [lst]})
    tree = client.get("/todos/tree").json()
    assert tree["todosById"][x]["blocked"] is False
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Edit `app/db_firestore.py`** — add `types` to the `from app import ...` line. Replace the `all_done`/`check` block and the loop in `clear_completed`:

```python
    memo: dict[str, tuple[bool, bool]] = {}
    def check(tid: str) -> tuple[bool, bool]:
        """(everything beneath is done, a todo is here or beneath). A container's own
        `done` means nothing, so only its todos decide."""
        if tid not in memo:
            memo[tid] = (False, False)  # cycle guard
            data = live[tid]
            kids = [check(c) for c in children.get(tid, [])]
            has_state = types.can_type(data.get("type"), "hasCheckbox")
            memo[tid] = (all(k[0] for k in kids) and (data.get("done", False) or not has_state),
                         has_state or any(k[1] for k in kids))
        return memo[tid]

    cleared = []
    pending = list(children.get(None, []))
    while pending:
        tid = pending.pop()
        all_done, has_todo = check(tid)
        if all_done and has_todo:
```

(the body of that `if` and the `else` stay as they are). In `get_tree` line ~574 change to:

```python
        todo.blocked = any(str(b) in live and not live[str(b)].done and types.can(live[str(b)], "hasCheckbox")
                           for b in todo.blocked_by)
```

- [ ] **Step 4: Run** `scripts/test.sh -q` — whole Python suite passes; `ruff check app tests` and `mypy` clean.
- [ ] **Step 5: Commit** — "Clear-completed and blocked ignore a container's own done".

---

### Task 6: Client registry (generated data + `Types`)

**Files:** Create `scripts/gen_types.py`, `web/types-data.js`, `web/types.js`, `tests_js/types.test.js`; Modify `web/index.html`; add stale test to `tests/test_item_types.py`.

**Produces:** `Types.get(item)`, `Types.can(item, flag)`, `Types.hasField(item, field)`, `Types.names`.

- [ ] **Step 1: Failing tests**

`tests/test_item_types.py`:

```python
def test_generated_client_data_is_current():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("gen_types", root / "scripts" / "gen_types.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (root / "web" / "types-data.js").read_text() == gen.render(), "run: python scripts/gen_types.py"
```

`tests_js/types.test.js`:

```js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Types = require("../web/types.js");

test("missing or unknown type behaves as todo", () => {
  assert.equal(Types.can({}, "hasCheckbox"), true);
  assert.equal(Types.can({ type: "from-the-future" }, "appearsInNextUp"), true);
});

test("containers have no checkbox and are not in badge, next up or autodone", () => {
  for (const type of ["list", "project"]) {
    for (const flag of ["hasCheckbox", "appearsInNextUp", "triggersAutodone", "countsInBadge"]) {
      assert.equal(Types.can({ type }, flag), false, `${type}.${flag}`);
    }
  }
  assert.equal(Types.can({ type: "project" }, "showsProgress"), true);
  assert.equal(Types.hasField({ type: "list" }, "due_date"), false);
  assert.equal(Types.hasField({ type: "todo" }, "due_date"), true);
});
```

- [ ] **Step 2: Run both, expect failures.**
- [ ] **Step 3: `scripts/gen_types.py`**

```python
"""Generate web/types-data.js from app/types.json (the one source of truth for item types).

Run after editing app/types.json:  python scripts/gen_types.py
tests/test_item_types.py fails when the checked-in file is stale."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def render() -> str:
    data = json.loads((ROOT / "app" / "types.json").read_text())
    body = json.dumps(data, indent=2)
    return f"""// GENERATED by scripts/gen_types.py from app/types.json. Do not edit.
(function (root, factory) {{
  if (typeof module === "object" && module.exports) {{
    module.exports = factory();
  }} else {{
    root.TypesData = factory();
  }}
}})(typeof self !== "undefined" ? self : this, function () {{
  "use strict";
  return {body};
}});
"""


if __name__ == "__main__":
    (ROOT / "web" / "types-data.js").write_text(render())
```

Run `python scripts/gen_types.py`.

- [ ] **Step 4: `web/types.js`**

```js
// Item types on the client: what a row of each type can do, from the registry data
// generated out of app/types.json. Feature code asks Types.can(item, flag) and never
// compares a type name. A missing or unknown type behaves as "todo".
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./types-data.js"));
  } else {
    root.Types = factory(root.TypesData);
  }
})(typeof self !== "undefined" ? self : this, function (data) {
  "use strict";

  const DEFAULT = "todo";
  const get = (item) => data[item && item.type] || data[DEFAULT];
  const can = (item, flag) => Boolean(get(item)[flag]);
  const hasField = (item, field) => get(item).fields.includes(field);

  return { get, can, hasField, names: Object.keys(data) };
});
```

- [ ] **Step 5: `web/index.html`** — right after the `config.js` script tag add, in this order, with the same `?v=` value the neighbours use:
`<script defer src="/types-data.js?v=76"></script>` then `<script defer src="/types.js?v=76"></script>`.
- [ ] **Step 6: Run** `node --test tests_js/*.test.js` and `scripts/test.sh tests/test_item_types.py -q` — pass.
- [ ] **Step 7: Commit** — "Add the client type registry generated from types.json".

---

### Task 7: Client guards — sync, badge, autodone

**Files:** Modify `web/sync.js`, `web/badge.js`, `web/autodone.js`; tests in `tests_js/sync.test.js`, `badge.test.js`, `autodone.test.js`.

**Consumes:** `Types` (Task 6). Each UMD module takes it as a factory argument: `module.exports = factory(require("./types.js"))` in Node, `factory(root.Types)` in the browser (scripts load in index order, and `types.js` is loaded first).

- [ ] **Step 1: Failing tests**

`tests_js/badge.test.js` (append):

```js
test("containers never count, whatever their due date", () => {
  const todos = [
    { done: false, due_date: "2026-01-01T00:00:00", type: "todo" },
    { done: false, due_date: "2026-01-01T00:00:00", type: "list" },
    { done: false, due_date: "2026-01-01T00:00:00", type: "project" },
  ];
  assert.equal(Badge.dueCount(todos, () => -1), 1);
});
```

`tests_js/autodone.test.js` (append; uses the file's `todo`/`modelOf` helpers):

```js
test("a container between two todos is transparent to autodone", () => {
  const m = modelOf(
    todo("g", { child_ids: ["p"] }),
    todo("p", { parent_id: "g", type: "project", child_ids: ["a", "b"] }),
    todo("a", { parent_id: "p", done: true }),
    todo("b", { parent_id: "p" }),
  );
  assert.deepEqual(Autodone.ancestorsToComplete(m, "b"), ["g"]);   // the project itself is never completed
});

test("an open todo under a container keeps the grandparent open", () => {
  const m = modelOf(
    todo("g", { child_ids: ["p"] }),
    todo("p", { parent_id: "g", type: "list", child_ids: ["a", "b"] }),
    todo("a", { parent_id: "p" }),
    todo("b", { parent_id: "p" }),
  );
  assert.deepEqual(Autodone.ancestorsToComplete(m, "b"), []);
});
```

`tests_js/sync.test.js` (append; use the file's existing helpers for a model and `applyOp`/`buildRequest` — read its top 40 lines first and mirror them):

```js
test("type is a patchable field: applied locally and sent", () => {
  const model = Sync.createModel();
  Sync.applyOp(model, { kind: "create", target_id: "a", payload: { title: "a" } });
  assert.equal(model.todosById.get("a").type, "todo");
  Sync.applyOp(model, { kind: "patch", target_id: "a", payload: { type: "list" } });
  assert.equal(model.todosById.get("a").type, "list");
  const req = Sync.buildRequest({ kind: "patch", target_id: "a", txn_id: "t", payload: { type: "list" } }, 3);
  assert.deepEqual(req.body, { type: "list" });
  assert.equal(req.headers["If-Match"], "3");
});

test("clearableIds: a container is cleared by its todos, not its own done", () => {
  const model = Sync.createModel();
  const mk = (id, extra) => { const n = { todo_id: id, done: false, child_ids: [], parent_id: null, type: "todo", ...extra };
    model.todosById.set(id, n); return n; };
  const proj = mk("proj", { type: "project", child_ids: ["t1"] });
  mk("t1", { done: true, parent_id: "proj" });
  const empty = mk("empty", { type: "list", done: true });
  model.roots = [proj, empty];
  assert.deepEqual(Sync.clearableIds(model), ["proj"]);
});
```

- [ ] **Step 2: Run `node --test tests_js/*.test.js`, expect the new tests to fail.**
- [ ] **Step 3: `web/badge.js`** — wrapper passes Types: `module.exports = factory(require("./types.js"));` / `root.Badge = factory(root.Types);`, `function (Types) {`. In `dueCount`: `if (!t.done && t.due_date && Types.can(t, "countsInBadge") && daysUntil(t) <= 0) n++;`.
- [ ] **Step 4: `web/autodone.js`** — same wrapper change; body:

```js
  // Every todo beneath `parent` is done (or about to be). Containers have no done state,
  // so they are looked through to the todos inside them.
  function allDone(model, parent, willBeDone) {
    return parent.child_ids.every((cid) => {
      const c = model.todosById.get(cid);
      if (!c) return true;
      if (!Types.can(c, "hasCheckbox")) return allDone(model, c, willBeDone);
      return c.done || willBeDone.has(cid);
    });
  }

  function ancestorsToComplete(model, id) {
    const out = [];
    const willBeDone = new Set([id]);
    let node = model.todosById.get(id);
    while (node && node.parent_id) {
      const parent = model.todosById.get(node.parent_id);
      if (!parent) break;
      if (Types.can(parent, "triggersAutodone")) {   // a container is passed through, never completed
        if (parent.done || !allDone(model, parent, willBeDone)) break;
        out.push(parent.todo_id);
        willBeDone.add(parent.todo_id);
      }
      node = parent;
    }
    return out;
  }
```

- [ ] **Step 5: `web/sync.js`** — same wrapper change (`factory(require("./types.js"))` / `factory(root.Types)`, `function (Types) {`). Add `"type"` to `PATCH_FIELDS`; add `type: "todo",` to `newNode`; replace `clearableIds`'s `allDone` with the same two-value derivation as the server:

```js
  function clearableIds(model) {
    const memo = new Map();
    // [everything beneath is done, a todo is here or beneath]; a container's own done means nothing.
    const check = (node) => {
      if (!memo.has(node.todo_id)) {
        memo.set(node.todo_id, [false, false]);
        const kids = node.child_ids.map((c) => model.todosById.get(c)).filter(Boolean).map(check);
        const hasState = Types.can(node, "hasCheckbox");
        memo.set(node.todo_id, [kids.every((k) => k[0]) && (!!node.done || !hasState),
                                hasState || kids.some((k) => k[1])]);
      }
      return memo.get(node.todo_id);
    };
    const out = [];
    const pending = model.roots.slice();
    while (pending.length) {
      const node = pending.pop();
      const [allDone, hasTodo] = check(node);
      if (allDone && hasTodo) out.push(node.todo_id);
      else node.child_ids.forEach((c) => { const n = model.todosById.get(c); if (n) pending.push(n); });
    }
    return out;
  }
```

- [ ] **Step 6: Run `node --test tests_js/*.test.js`** — all pass (existing sync tests still pass: their nodes have no `type`, which reads as todo).
- [ ] **Step 7: Commit** — "Badge, autodone and clear-completed follow the type registry on the client".

---

### Task 8: OKF bundle, full verification, ship

**Files:** Modify `docs/okf/data/todo.md`, `features/next-up.md`, `features/auto-done.md`, `features/trash-archive.md`, `features/push-reminders.md`, `features/calendar-feed.md`, `api/routes.md`, `architecture/code-map.md`, `ops/testing.md`, `index.md`, `log.md`; add `docs/okf/features/item-types.md` (`type: Feature`), linked from `index.md`.

- [ ] **Step 1:** Write `docs/okf/features/item-types.md`: the three types, the flags table, "container `done` is ignored", the single-source rule (`app/types.json` → `scripts/gen_types.py` → `web/types-data.js`, stale-file test), `PATCH type` semantics, missing/unknown reads as todo, slice status (pickers and progress in later slices).
- [ ] **Step 2:** In each affected file above add one or two lines pointing to `item-types.md` and stating the changed rule; bump every touched file's `timestamp` to now (UTC); append to `log.md`: `2026-09-21 — item types slice 1: registry, Todo.type, capability guards (next up, push, heads-ups, ICS, clear-completed, blocked, badge, autodone)`.
- [ ] **Step 3: Full verification** — `scripts/test.sh -q`, `node --test tests_js/*.test.js`, `ruff check app tests`, `mypy`. All must pass; paste no claims without the output.
- [ ] **Step 4: Commit** the OKF changes (the `okf-reminder` hook warns if code changed without docs).
- [ ] **Step 5: Push and deploy** — `git push`, then `./deploy.sh`; confirm it finishes, then `say "Item types slice one is deployed"`.
- [ ] **Step 6:** Smoke check on the live app: create a todo, `PATCH` its type to `list` and back with the UI unaffected (rows still render as todos in slice 1), and confirm Next Up and the badge still work.

---

## Self-review (against the spec)

- Registry + single source + stale test → Tasks 1, 6. `Todo.type`, default, unknown-safe reads, PATCH → Task 2.
- Next Up, push, heads-ups, ICS, clear-completed, blocked, spawn (type preserved by `doc_to_todo`/`todo_to_doc`) → Tasks 3–5, 2.
- Badge, autodone, client clear-completed → Task 7. `PATCH_FIELDS` + conflict rebase come for free from that list.
- Explicitly out of slice 1 (in later plans): row checkbox and done-sink, pickers, dynamic edit sheet, progress readout, renderers.
- Names used consistently: `can`, `can_type`, `has_field`, `caps`, `NAMES`, `Types.can/hasField/get`, `item_type`.
