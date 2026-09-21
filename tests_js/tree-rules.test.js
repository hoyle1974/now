"use strict";
// The client half of tests/test_tree_rules.py: the same tree fixture must give the same
// clearable and blocked ids here as on the server.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Sync = require("../web/sync.js");
const Fields = require("../web/fields.js");

const { cases } = JSON.parse(fs.readFileSync(path.join(__dirname, "../tests/fixtures/tree_rules.json"), "utf8"));

// Deleted nodes are not in the client model at all, and never appear in a parent's child_ids.
function load(nodes) {
  const model = Sync.createModel();
  const live = nodes.filter((n) => !n.deleted);
  for (const n of live) {
    model.todosById.set(n.id, {
      todo_id: n.id, title: n.id, type: n.type, done: n.done, deleted: false,
      parent_id: n.parent || null, child_ids: [], blocked_by: n.blocked_by || [], order_idx: null,
    });
  }
  for (const n of live) {
    const node = model.todosById.get(n.id);
    if (n.parent) model.todosById.get(n.parent).child_ids.push(n.id);
    else model.roots.push(node);
  }
  return model;
}

for (const c of cases) {
  test(`tree rules: ${c.name}`, () => {
    const model = load(c.nodes);
    const blocked = c.nodes.map((n) => n.id).filter((id) => {
      const node = model.todosById.get(id);
      return node && Fields.isBlocked(node, model.todosById);
    });
    assert.deepEqual(blocked.sort(), [...c.blocked].sort());
    assert.deepEqual(Sync.clearableIds(model).sort(), [...c.clearable].sort());
  });
}
