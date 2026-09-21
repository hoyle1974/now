"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const DatePicker = require("../web/date-picker.js");

test("chipState lights Today, Tomorrow, or Pick date for any other date", () => {
  const t = "2026-09-21", m = "2026-09-22";
  assert.deepEqual(DatePicker.chipState(t, t, m), { today: true, tomorrow: false, custom: false });
  assert.deepEqual(DatePicker.chipState(m, t, m), { today: false, tomorrow: true, custom: false });
  assert.deepEqual(DatePicker.chipState("2026-10-01", t, m), { today: false, tomorrow: false, custom: true });
  assert.deepEqual(DatePicker.chipState("", t, m), { today: false, tomorrow: false, custom: false });
});
