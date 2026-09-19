"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Sync = require("../web/sync.js");

function todo(id, extra = {}) {
  return {
    todo_id: id, title: id, done: false, create_date: "2026-01-01T00:00:00",
    due_date: null, order_idx: 0, parent_id: null, child_ids: [], deleted: false,
    version: 1, ...extra,
  };
}

function modelOf(...todos) {
  const model = Sync.createModel();
  for (const t of todos) model.todosById.set(t.todo_id, t);
  for (const t of todos) {
    if (t.parent_id) model.todosById.get(t.parent_id).child_ids.push(t.todo_id);
    else model.roots.push(t);
  }
  return model;
}

// a: done leaf. b: done with an open child. c: done, done child. d: open with a done child.
function sample() {
  return modelOf(
    todo("a", { done: true }),
    todo("b", { done: true }), todo("b1", { parent_id: "b" }),
    todo("c", { done: true }), todo("c1", { parent_id: "c", done: true }),
    todo("d"), todo("d1", { parent_id: "d", done: true }),
  );
}

test("clearableIds picks topmost fully-done subtrees only", () => {
  assert.deepEqual(Sync.clearableIds(sample()).sort(), ["a", "c", "d1"]);
});

test("clear_completed applies locally and can be undone per item", () => {
  const model = sample();
  assert.equal(Sync.applyOp(model, { kind: "clear_completed", target_id: "clear-completed" }), true);
  assert.deepEqual([...model.todosById.keys()].sort(), ["b", "b1", "d"]);
  assert.deepEqual(model.todosById.get("d").child_ids, []);
  assert.equal(Sync.applyOp(model, { kind: "undelete", target_id: "c" }), true);
  assert.ok(model.todosById.has("c") && model.todosById.has("c1"));
});

test("clear_completed with nothing to clear does not apply", () => {
  const model = modelOf(todo("a"));
  assert.equal(Sync.applyOp(model, { kind: "clear_completed", target_id: "clear-completed" }), false);
});

test("clear_completed request is an unconditional POST with the txn id", () => {
  const req = Sync.buildRequest({ kind: "clear_completed", target_id: "clear-completed", txn_id: "t1", payload: {} }, 5);
  assert.equal(req.method, "POST");
  assert.equal(req.path, "/todos/clear-completed");
  assert.equal(req.headers["X-Txn-Id"], "t1");
  assert.equal(req.headers["If-Match"], undefined);
});

test("engine sends one clear-completed request and drains", async () => {
  const model = sample();
  const sent = [];
  const engine = Sync.createEngine({
    model,
    store: { async load() { return []; }, async save() {} },
    send: async (req) => { sent.push(req); return { status: 200, body: { cleared: [] } }; },
    refetch: async () => { throw new Error("no refetch"); },
  });
  assert.ok(engine.enqueue({ kind: "clear_completed", target_id: "clear-completed" }));
  await engine.flush();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].path, "/todos/clear-completed");
  assert.equal(engine.pending(), 0);
});
