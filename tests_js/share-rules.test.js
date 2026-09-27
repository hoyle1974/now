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

// ---- the Sharing control in the viewer ----------------------------------------------

function shareModel() {
  const S = { id: "S", owner: ME, mode: "rw" };
  const O = { id: "O", owner: "owner@x.com", mode: "rw" };
  const nodes = [
    { todo_id: "trip", type: "list", child_ids: ["t1"] },
    { todo_id: "t1", type: "todo", parent_id: "trip", child_ids: [] },
    { todo_id: "cals", type: "list", child_ids: ["cal"] },
    { todo_id: "cal", type: "calendar", parent_id: "cals", child_ids: [] },
    { todo_id: "S", type: "list", share: S, share_root: true, child_ids: ["s1"] },
    { todo_id: "s1", type: "todo", parent_id: "S", share: S, child_ids: [] },
    { todo_id: "O", type: "list", share: O, share_root: true, child_ids: [] },
    { todo_id: "holder", type: "list", child_ids: ["O"] },
    { todo_id: "tmp:1", type: "todo", child_ids: [] },
  ];
  return { todosById: new Map(nodes.map((n) => [n.todo_id, n])) };
}
const shareable = (n) => ["todo", "list", "project", "note"].includes(n.type);
const row = (id, online = true) => {
  const m = shareModel();
  return ShareUI.sharingRow(m, m.todosById.get(id), ME, online, shareable);
};

test("sharing row: private items of plain types can be shared", () => {
  assert.deepEqual(row("trip"), { visible: true, value: "private", disabledReason: null });
});

test("sharing row: your own share shows its mode; someone else's and nodes inside a share show nothing", () => {
  assert.deepEqual(row("S"), { visible: true, value: "rw", disabledReason: null });
  assert.equal(row("O").visible, false);
  assert.equal(row("s1").visible, false);
});

test("sharing row: hidden for calendars, subtrees holding one or a share, and unsynced items", () => {
  assert.equal(row("cal").visible, false);
  assert.equal(row("cals").visible, false);
  assert.equal(row("holder").visible, false);
  assert.equal(row("tmp:1").visible, false);
});

test("sharing row: offline says why it can't change", () => {
  assert.deepEqual(row("trip", false), { visible: true, value: "private", disabledReason: "Go online to change sharing" });
});
