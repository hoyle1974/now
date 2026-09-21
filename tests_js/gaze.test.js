"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
require("../web/mascot.js");
const { fromTilt, max } = globalThis.Mascot.gaze;

test("upright phone rests centred sideways", () => {
  assert.ok(Math.abs(fromTilt(0, 9.81, false).x) < 1e-9);
});
test("tilting right edge down looks right (Android sign)", () => {
  assert.ok(fromTilt(-5, 9, false).x > 0);
});
test("iOS reports the opposite sign, same result", () => {
  assert.ok(fromTilt(5, -9, true).x > 0);
  assert.equal(fromTilt(5, -9, true).y, fromTilt(-5, 9, false).y);
});
test("gaze is clamped to the eye edge", () => {
  const g = fromTilt(-50, 50, false);
  assert.ok(Math.abs(g.x) <= max && Math.abs(g.y) <= max);
});
