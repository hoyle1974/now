"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Autodone = require("../web/autodone.js");

const todo = (id, extra = {}) => ({ todo_id: id, done: false, parent_id: null, child_ids: [], ...extra });
const modelOf = (...nodes) => ({ todosById: new Map(nodes.map((n) => [n.todo_id, n])), roots: nodes.filter((n) => !n.parent_id) });

test("completing the last open child completes its parent", () => {
  const m = modelOf(todo("p", { child_ids: ["a", "b"] }), todo("a", { parent_id: "p", done: true }), todo("b", { parent_id: "p" }));
  assert.deepEqual(Autodone.ancestorsToComplete(m, "b"), ["p"]);
});

test("nothing happens while a sibling is still open", () => {
  const m = modelOf(todo("p", { child_ids: ["a", "b"] }), todo("a", { parent_id: "p" }), todo("b", { parent_id: "p" }));
  assert.deepEqual(Autodone.ancestorsToComplete(m, "b"), []);
});

test("it cascades up through ancestors whose children are all done", () => {
  const m = modelOf(
    todo("g", { child_ids: ["p", "q"] }),
    todo("p", { parent_id: "g", child_ids: ["a"] }), todo("a", { parent_id: "p" }),
    todo("q", { parent_id: "g", done: true }),
  );
  assert.deepEqual(Autodone.ancestorsToComplete(m, "a"), ["p", "g"]);
});

test("it stops at the first ancestor that still has an open child", () => {
  const m = modelOf(
    todo("g", { child_ids: ["p", "q"] }),
    todo("p", { parent_id: "g", child_ids: ["a"] }), todo("a", { parent_id: "p" }),
    todo("q", { parent_id: "g" }),
  );
  assert.deepEqual(Autodone.ancestorsToComplete(m, "a"), ["p"]);
});

test("an already-done parent is left alone", () => {
  const m = modelOf(todo("p", { done: true, child_ids: ["a"] }), todo("a", { parent_id: "p" }));
  assert.deepEqual(Autodone.ancestorsToComplete(m, "a"), []);
});

test("a root or unknown todo has no ancestors to complete", () => {
  const m = modelOf(todo("a"));
  assert.deepEqual(Autodone.ancestorsToComplete(m, "a"), []);
  assert.deepEqual(Autodone.ancestorsToComplete(m, "zzz"), []);
});
