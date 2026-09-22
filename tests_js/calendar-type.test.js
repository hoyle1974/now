"use strict";
const test = require("node:test");
const assert = require("node:assert");
const Types = require("../web/types.js");

test("calendar_event is read-only and cannot take user children", () => {
  const ev = { type: "calendar_event" };
  assert.strictEqual(Types.can(ev, "editable"), false);
  assert.strictEqual(Types.can(ev, "allowsUserChildren"), false);
  assert.strictEqual(Types.hasField(ev, "location"), true);
});

test("calendar accepts edits but not manually added children", () => {
  const cal = { type: "calendar" };
  assert.strictEqual(Types.can(cal, "editable"), true);
  assert.strictEqual(Types.can(cal, "allowsUserChildren"), false);
  assert.strictEqual(Types.hasField(cal, "calendar_url"), true);
});
