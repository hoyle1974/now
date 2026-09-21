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

test("formatRepeat reads naturally", () => {
  assert.equal(Due.formatRepeat({ unit: "day", every: 1 }), "Daily");
  assert.equal(Due.formatRepeat({ unit: "week", every: 1 }), "Weekly");
  assert.equal(Due.formatRepeat({ unit: "month", every: 1 }), "Monthly");
  assert.equal(Due.formatRepeat({ unit: "year", every: 1 }), "Yearly");
  assert.equal(Due.formatRepeat({ unit: "weekday", every: 1 }), "Weekdays");
  assert.equal(Due.formatRepeat({ unit: "week", every: 2 }), "Every 2 weeks");
  assert.equal(Due.formatRepeat({ unit: "day", every: 3 }), "Every 3 days");
  assert.equal(Due.formatRepeat(null), "");
});

// A fixed "now" (local time) so the calendar helpers are testable.
const NOW = new Date(2026, 8, 21, 15, 0); // Mon 21 Sep 2026, 3pm

test("today and tomorrow are local YYYY-MM-DD, across month and year ends", () => {
  assert.equal(Due.today(NOW), "2026-09-21");
  assert.equal(Due.tomorrow(NOW), "2026-09-22");
  assert.equal(Due.tomorrow(new Date(2026, 8, 30, 23, 59)), "2026-10-01");
  assert.equal(Due.tomorrow(new Date(2026, 11, 31, 8, 0)), "2027-01-01");
});

test("daysUntil counts calendar days, ignoring the time of day", () => {
  assert.equal(Due.daysUntil("2026-09-21T00:00:00", NOW), 0);
  assert.equal(Due.daysUntil("2026-09-21T23:30:00", NOW), 0);
  assert.equal(Due.daysUntil("2026-09-22T00:00:00", NOW), 1);
  assert.equal(Due.daysUntil("2026-09-20T23:59:00", NOW), -1);
  assert.equal(Due.daysUntil("2026-09-14T00:00:00", NOW), -7);
});

test("formatDay: relative for the near term, a date beyond a week", () => {
  const f = (iso) => Due.formatDay(iso, NOW);
  assert.equal(f("2026-09-21T00:00:00"), "Today");
  assert.equal(f("2026-09-22T00:00:00"), "Tomorrow");
  assert.equal(f("2026-09-20T00:00:00"), "Yesterday");
  assert.equal(f("2026-09-18T00:00:00"), "3 days overdue");
  assert.ok(f("2026-09-25T00:00:00").length > 0);                       // a weekday name
  assert.ok(!/2026/.test(f("2026-10-15T00:00:00")));                    // same year: no year
  assert.ok(/2027/.test(f("2027-01-15T00:00:00")));                     // other year: year shown
});

test("format adds the time only for a timed due, and not for far-overdue ones", () => {
  assert.equal(Due.format("2026-09-21T00:00:00", NOW), "Today");
  assert.match(Due.format("2026-09-21T16:30:00", NOW), /^Today .*4:30|^Today .*16:30/);
  assert.equal(Due.format("2026-09-15T16:30:00", NOW), "6 days overdue");
});
