"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Outline = require("../web/outline.js");

const todo = (id, title, extra = {}) => ({ todo_id: id, title, done: false, child_ids: [], ...extra });
const byId = (...todos) => new Map(todos.map((t) => [t.todo_id, t]));

test("a lone todo is a single bullet", () => {
  assert.equal(Outline.toOutline(byId(todo("a", "Buy milk")), "a"), "- Buy milk");
});

test("children are indented two spaces per level and ordered by order_idx", () => {
  const m = byId(
    todo("a", "Trip", { child_ids: ["b", "c"] }),
    todo("b", "Pack", { order_idx: 2, child_ids: ["d"] }),
    todo("c", "Book flights", { order_idx: 1 }),
    todo("d", "Socks"),
  );
  assert.equal(Outline.toOutline(m, "a"), "- Trip\n  - Book flights\n  - Pack\n    - Socks");
});

test("done items are marked and only the chosen subtree is copied", () => {
  const m = byId(
    todo("a", "Root", { child_ids: ["b"] }),
    todo("b", "Sub", { done: true, child_ids: ["c"] }),
    todo("c", "Leaf"),
  );
  assert.equal(Outline.toOutline(m, "b"), "- [x] Sub\n  - Leaf");
});
