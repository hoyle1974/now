"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const EventLog = require("../web/eventlog.js");

function fakeStorage(initial = {}) {
  const data = { ...initial };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); } };
}

test("records entries in order with time, kind and detail", () => {
  let t = 1000;
  const log = EventLog.create({ storage: fakeStorage(), now: () => t });
  log.log("visibility", "hidden");
  t += 500;
  log.log("rev", { server: 8, known: 5 });
  assert.deepEqual(log.entries().map((e) => [e.t, e.k, e.d]), [
    [1000, "visibility", "hidden"],
    [1500, "rev", '{"server":8,"known":5}'],
  ]);
});

test("keeps only the most recent max entries", () => {
  const log = EventLog.create({ storage: fakeStorage(), max: 3, now: () => 0 });
  for (let i = 0; i < 10; i++) log.log("e", String(i));
  assert.deepEqual(log.entries().map((e) => e.d), ["7", "8", "9"]);
});

test("persists across instances (the page can be killed and reloaded)", () => {
  const storage = fakeStorage();
  EventLog.create({ storage, now: () => 1 }).log("visibility", "hidden");
  const again = EventLog.create({ storage, now: () => 2 });
  assert.equal(again.entries().length, 1);
  again.log("load", "fresh");
  assert.deepEqual(EventLog.create({ storage }).entries().map((e) => e.k), ["visibility", "load"]);
});

test("clear empties memory and storage", () => {
  const storage = fakeStorage();
  const log = EventLog.create({ storage, now: () => 1 });
  log.log("a", "b");
  log.clear();
  assert.equal(log.entries().length, 0);
  assert.equal(EventLog.create({ storage }).entries().length, 0);
});

test("survives a broken or throwing storage", () => {
  const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("quota"); } };
  const log = EventLog.create({ storage: throwing, now: () => 1 });
  log.log("a", "b");
  assert.equal(log.entries().length, 1);
  const junk = EventLog.create({ storage: fakeStorage({ "todo-event-log": "{not json" }) });
  assert.deepEqual(junk.entries(), []);
  assert.doesNotThrow(() => EventLog.create({ storage: null }).log("a", "b"));
});

test("long details are truncated", () => {
  const log = EventLog.create({ storage: fakeStorage(), now: () => 1 });
  log.log("big", "x".repeat(1000));
  assert.ok(log.entries()[0].d.length <= 200);
});

test("format shows newest first with the gap since the previous entry", () => {
  let t = new Date(2026, 8, 18, 19, 41, 7, 123).getTime();
  const log = EventLog.create({ storage: fakeStorage(), now: () => t });
  log.log("visibility", "hidden");
  t += 250;
  log.log("focus", "");
  t += 125_000;
  log.log("visibility", "visible");
  const lines = log.format().split("\n");
  assert.match(lines[0], /09-18 19:43:12\.373\s+\+2m05s\s+visibility\s+visible/);
  assert.match(lines[1], /19:41:07\.373\s+\+250ms\s+focus/);
  assert.match(lines[2], /19:41:07\.123\s+visibility\s+hidden/);
});

test("gap formatting covers ms, seconds, minutes and hours", () => {
  assert.equal(EventLog.formatGap(40), "+40ms");
  assert.equal(EventLog.formatGap(2300), "+2.3s");
  assert.equal(EventLog.formatGap(125000), "+2m05s");
  assert.equal(EventLog.formatGap(3720000), "+1h02m");
});

test("subscribers are told about new entries and clears", () => {
  const log = EventLog.create({ storage: fakeStorage(), now: () => 1 });
  let n = 0;
  const off = log.subscribe(() => n++);
  log.log("a", "b");
  log.clear();
  assert.equal(n, 2);
  off();
  log.log("c", "d");
  assert.equal(n, 2);
});
