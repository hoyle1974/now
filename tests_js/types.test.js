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
