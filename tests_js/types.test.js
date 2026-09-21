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
