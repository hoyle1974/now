"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Due = require("../web/due.js");

test("hasTime: midnight means all-day, any other time is timed", () => {
  assert.equal(Due.hasTime("2026-09-19T00:00:00"), false);
  assert.equal(Due.hasTime("2026-09-19T00:00"), false);
  assert.equal(Due.hasTime("2026-09-19T15:30:00"), true);
  assert.equal(Due.hasTime("2026-09-19T00:05:00"), true);
  assert.equal(Due.hasTime(null), false);
  assert.equal(Due.hasTime("2026-09-19"), false);
});

test("timePart gives HH:MM for timed dues and empty for all-day", () => {
  assert.equal(Due.timePart("2026-09-19T15:30:00"), "15:30");
  assert.equal(Due.timePart("2026-09-19T09:05:59"), "09:05");
  assert.equal(Due.timePart("2026-09-19T00:00:00"), "");
  assert.equal(Due.timePart(null), "");
});

test("combine joins a date and optional time, and needs a date", () => {
  assert.equal(Due.combine("2026-09-19", "15:30"), "2026-09-19T15:30:00");
  assert.equal(Due.combine("2026-09-19", ""), "2026-09-19");
  assert.equal(Due.combine("", "15:30"), "");
  assert.equal(Due.combine("", ""), "");
});

test("isOverdue: all-day is overdue after its day, timed once the time passes", () => {
  const now = new Date(2026, 8, 19, 12, 0, 0); // Sep 19 12:00 local
  assert.equal(Due.isOverdue("2026-09-19T00:00:00", now), false); // all-day today
  assert.equal(Due.isOverdue("2026-09-18T00:00:00", now), true);  // all-day yesterday
  assert.equal(Due.isOverdue("2026-09-19T15:30:00", now), false); // later today
  assert.equal(Due.isOverdue("2026-09-19T09:00:00", now), true);  // earlier today
  assert.equal(Due.isOverdue("2026-09-20T09:00:00", now), false);
  assert.equal(Due.isOverdue(null, now), false);
});
