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

test("descendantCounts counts only todos, at any depth, looking through containers", () => {
  const node = (id, extra = {}) => [id, { todo_id: id, done: false, child_ids: [], type: "todo", ...extra }];
  const byId = new Map([
    node("proj", { type: "project", child_ids: ["a", "lst", "empty"] }),
    node("a", { done: true }),
    node("lst", { type: "list", child_ids: ["b", "c"] }),
    node("b", { done: true }), node("c"),
    node("empty", { type: "list" }),
  ]);
  const counts = Types.descendantCounts(byId);
  assert.deepEqual(counts.get("proj"), { total: 3, done: 2 });
  assert.deepEqual(counts.get("lst"), { total: 2, done: 1 });
  assert.deepEqual(counts.get("empty"), { total: 0, done: 0 });
});

test("inherited object keys are not types", () => {
  assert.equal(Types.can({ type: "constructor" }, "hasCheckbox"), true);
  assert.equal(Types.hasField({ type: "toString" }, "due_date"), true);
  assert.equal(Types.nameOf({ type: "__proto__" }), "todo");
});

test("defaultChildType: newest sibling wins, then the parent's default, then todo", () => {
  const sib = (type, when, extra = {}) => ({ type, create_date: when, deleted: false, ...extra });
  const parent = { type: "project" };
  assert.equal(Types.defaultChildType(parent, []), "todo");
  assert.equal(Types.defaultChildType(parent, [sib("list", "2026-01-01"), sib("todo", "2026-01-02")]), "todo");
  assert.equal(Types.defaultChildType(parent, [sib("todo", "2026-01-01"), sib("list", "2026-01-02")]), "list");
  // Order in the array does not matter; only create_date does.
  assert.equal(Types.defaultChildType(parent, [sib("list", "2026-01-02"), sib("todo", "2026-01-01")]), "list");
  assert.equal(Types.defaultChildType(parent, [sib("list", "2026-01-02", { deleted: true }), sib("todo", "2026-01-01")]), "todo");
  assert.equal(Types.defaultChildType(null, [sib("project", "2026-01-01")]), "project");
  assert.equal(Types.defaultChildType(null, []), "todo");
  assert.equal(Types.defaultChildType(parent, [sib("from-the-future", "2026-01-01")]), "todo");
});

test("every type has a label, description, icon and a known default child type", () => {
  for (const name of Types.names) {
    const t = Types.get({ type: name });
    assert.ok(t.label && t.description && t.icon, name);
    assert.ok(Types.names.includes(t.defaultChildType), name);
  }
});
