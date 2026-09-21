"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Badge = require("../web/badge.js");

const days = (t) => t.days; // stand-in for daysUntil: the todo carries its own offset
const todo = (extra) => ({ done: false, due_date: "x", days: 0, ...extra });

test("counts open todos due today or overdue", () => {
  const todos = [todo({ days: 0 }), todo({ days: -3 }), todo({ days: 1 }), todo({ due_date: null })];
  assert.equal(Badge.dueCount(todos, days), 2);
});

test("done todos are not counted", () => {
  assert.equal(Badge.dueCount([todo({ done: true }), todo()], days), 1);
});

test("apply sets the badge to the count, and clears it at zero", async () => {
  const calls = [];
  const nav = { setAppBadge: async (n) => calls.push(["set", n]), clearAppBadge: async () => calls.push(["clear"]) };
  await Badge.apply(nav, 3);
  await Badge.apply(nav, 0);
  assert.deepEqual(calls, [["set", 3], ["clear"]]);
});

test("apply is a quiet no-op where the Badging API is missing", async () => {
  await Badge.apply({}, 2);
});

test("apply swallows a rejected badge call (e.g. permission not granted)", async () => {
  const nav = { setAppBadge: async () => { throw new Error("NotAllowedError"); } };
  await Badge.apply(nav, 2);
});

test("canPrompt is true only where a permission ask can help", () => {
  const nav = { setAppBadge() {} };
  assert.equal(Badge.canPrompt(nav, { permission: "default" }), true);
  assert.equal(Badge.canPrompt(nav, { permission: "granted" }), false);
  assert.equal(Badge.canPrompt(nav, { permission: "denied" }), false);
  assert.equal(Badge.canPrompt(nav, undefined), false);
  assert.equal(Badge.canPrompt({}, { permission: "default" }), false);
});

test("containers never count, whatever their due date", () => {
  const todos = [
    { done: false, due_date: "2026-01-01T00:00:00", type: "todo" },
    { done: false, due_date: "2026-01-01T00:00:00", type: "list" },
    { done: false, due_date: "2026-01-01T00:00:00", type: "project" },
  ];
  assert.equal(Badge.dueCount(todos, () => -1), 1);
});
