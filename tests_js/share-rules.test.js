"use strict";
// The client's reading of the sharing permissions must match the server's: both are
// checked against tests/fixtures/share_rules.json (server: tests/test_share_rules.py).
const test = require("node:test");
const assert = require("node:assert/strict");
const RULES = require("../tests/fixtures/share_rules.json");
const ShareUI = require("../web/share-ui.js");

const ME = "me@x.com";
const nodeFor = (role, extra = {}) => ({
  todo_id: "c", share: { id: "S", owner: role === "owner" ? ME : "owner@x.com", mode: role === "ro" ? "ro" : "rw" },
  ...extra,
});

// A client only ever holds shares it can see, so stranger/revoked never reach it.
for (const role of ["owner", "rw", "ro"]) {
  for (const [action, allowed] of Object.entries(RULES.actions)) {
    test(`${action} for ${role} matches the fixture`, () => {
      assert.equal(ShareUI.can(nodeFor(role), action, ME), allowed[role]);
    });
  }
}

test("an item of your own allows everything", () => {
  for (const action of Object.keys(RULES.actions)) assert.equal(ShareUI.can({ todo_id: "x" }, action, ME), true);
});

test("badge label only on the root; by names someone else", () => {
  assert.deepEqual(ShareUI.badge(nodeFor("rw", { share_root: true }), ME),
    { icon: true, label: "Shared · can edit", by: "owner" });
  assert.deepEqual(ShareUI.badge(nodeFor("ro", { share_root: true }), ME),
    { icon: true, label: "Shared · read-only", by: "owner" });
  assert.deepEqual(ShareUI.badge(nodeFor("owner", { share_root: true }), ME),
    { icon: true, label: "Shared · can edit", by: null });
  assert.deepEqual(ShareUI.badge(nodeFor("rw"), ME), { icon: true, label: null, by: null });
  assert.equal(ShareUI.badge({ todo_id: "x" }, ME), null);
});

test("editable tells a row whether to offer edits", () => {
  assert.equal(ShareUI.editable(nodeFor("ro"), ME), false);
  assert.equal(ShareUI.editable(nodeFor("rw"), ME), true);
  assert.equal(ShareUI.editable(nodeFor("owner"), ME), true);
  assert.equal(ShareUI.editable({ todo_id: "x" }, ME), true);
});

function model() {
  const S = { id: "S", owner: "owner@x.com", mode: "rw" };
  const T = { id: "T", owner: ME, mode: "ro" };
  const nodes = [
    { todo_id: "home", parent_id: null, child_ids: ["S"] },
    { todo_id: "S", parent_id: "home", share: S, share_root: true, child_ids: ["c"] },
    { todo_id: "c", parent_id: "S", share: S, child_ids: [] },
    { todo_id: "T", parent_id: null, share: T, share_root: true, child_ids: ["t1"] },
    { todo_id: "t1", parent_id: "T", share: T, child_ids: [] },
  ];
  return { todosById: new Map(nodes.map((n) => [n.todo_id, n])) };
}

test("crossesEdge sees drags into, out of and within a share", () => {
  const m = model();
  assert.deepEqual(ShareUI.crossesEdge(m, "home", "S"), { crosses: true, into: "S", outOf: null, allowed: true });
  assert.deepEqual(ShareUI.crossesEdge(m, "c", null), { crosses: true, into: null, outOf: "S", allowed: true });
  assert.deepEqual(ShareUI.crossesEdge(m, "c", "S"), { crosses: false, into: null, outOf: null, allowed: true });
  assert.deepEqual(ShareUI.crossesEdge(m, "S", null), { crosses: false, into: null, outOf: null, allowed: true },
    "a share root moves as your mount");
  assert.equal(ShareUI.crossesEdge(m, "S", "t1").allowed, false, "a mount never goes inside a share");
  assert.equal(ShareUI.crossesEdge(m, "c", "t1").allowed, true, "share to share: out of S, into T");
});

test("dropAllowed refuses read-only shares on either side", () => {
  const m = model();
  m.todosById.get("T").share.owner = "owner@x.com";
  m.todosById.get("t1").share = m.todosById.get("T").share;
  assert.equal(ShareUI.dropAllowed(m, "home", "t1", ME), false, "into a read-only share");
  assert.equal(ShareUI.dropAllowed(m, "t1", null, ME), false, "out of a read-only share");
  assert.equal(ShareUI.dropAllowed(m, "home", "S", ME), true);
  assert.equal(ShareUI.dropAllowed(m, "T", null, ME), true, "your mount of a read-only share still moves");
});

test("crossing confirm text names the item", () => {
  const m = model();
  m.todosById.get("home").title = "Buy cake";
  m.todosById.get("c").title = "Milk";
  assert.equal(ShareUI.crossingMessage(m, "home", "S"), "Everyone will see “Buy cake”.");
  assert.equal(ShareUI.crossingMessage(m, "c", null), "This removes “Milk” for everyone else.");
  assert.equal(ShareUI.crossingMessage(m, "c", "S"), null);
});
