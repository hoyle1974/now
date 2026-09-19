"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Freshness = require("../web/freshness.js");

function setup({ serverRev = 5, knownRev = 5, pending = 0, editor = false, revFails = false, active = true } = {}) {
  const s = { serverRev, knownRev, pending, editor, revFails, active, stale: false,
    revFetches: 0, refreshes: 0, clock: 1_000_000, timers: [], phases: [] };
  const engine = {
    pending: () => s.pending,
    isStale: () => s.stale,
    noteRemoteRev: (rev) => { if (rev > s.knownRev) s.stale = true; },
  };
  const f = Freshness.create({
    engine,
    fetchRev: async () => { s.revFetches++; if (s.revFails) throw new Error("offline"); return s.serverRev; },
    refresh: async () => { s.refreshes++; s.knownRev = s.serverRev; s.stale = false; },
    editorOpen: () => s.editor,
    now: () => s.clock,
    minGapMs: 30000,
    isActive: () => s.active,
    onPhase: (p) => s.phases.push(p),
    timers: {
      setTimeout: (fn, ms) => { s.timers.push({ fn, ms, live: true }); return s.timers.length - 1; },
      clearTimeout: (id) => { if (s.timers[id]) s.timers[id].live = false; },
    },
  });
  s.fireRetry = async () => { const t = s.timers.filter((x) => x.live).pop(); t.live = false; await t.fn(); };
  s.liveTimers = () => s.timers.filter((x) => x.live);
  return { s, f };
}

test("no refresh when the server revision matches ours", async () => {
  const { s, f } = setup();
  s.clock += 60000;
  await f.check();
  assert.equal(s.revFetches, 1);
  assert.equal(s.refreshes, 0);
});

test("refreshes when the server is ahead", async () => {
  const { s, f } = setup({ serverRev: 7 });
  s.clock += 60000;
  await f.check();
  assert.equal(s.refreshes, 1);
  assert.equal(s.knownRev, 7);
});

test("a check right after creation is skipped (the page just loaded)", async () => {
  const { s, f } = setup({ serverRev: 9 });
  await f.check();
  assert.equal(s.revFetches, 0);
});

test("checks are debounced to one per 30s, then allowed again", async () => {
  const { s, f } = setup();
  s.clock += 60000;
  await f.check();
  s.clock += 5000;
  await f.check();
  await f.check();
  assert.equal(s.revFetches, 1);
  s.clock += 30000;
  await f.check();
  assert.equal(s.revFetches, 2);
});

test("with edits pending it asks nothing, then checks once the queue drains", async () => {
  const { s, f } = setup({ serverRev: 8, pending: 2 });
  s.clock += 60000;
  await f.check();
  assert.equal(s.revFetches, 0);
  assert.equal(s.refreshes, 0);
  s.pending = 0;
  await f.poke();
  assert.equal(s.revFetches, 1);
  assert.equal(s.refreshes, 1);
});

test("an open editor defers the refresh until it closes", async () => {
  const { s, f } = setup({ serverRev: 8, editor: true });
  s.clock += 60000;
  await f.check();
  assert.equal(s.refreshes, 0);
  await f.poke();
  assert.equal(s.refreshes, 0, "still open");
  s.editor = false;
  await f.poke();
  assert.equal(s.refreshes, 1);
});

test("poke does nothing when nothing is waiting", async () => {
  const { s, f } = setup();
  s.clock += 60000;
  await f.poke();
  await f.poke();
  assert.equal(s.revFetches, 0);
  assert.equal(s.refreshes, 0);
});

test("a stale flag from a write response refreshes without asking the server", async () => {
  const { s, f } = setup({ serverRev: 7 });
  s.stale = true;
  await f.poke();
  assert.equal(s.revFetches, 0);
  assert.equal(s.refreshes, 1);
});

test("a stale flag bypasses the debounce on the next focus", async () => {
  const { s, f } = setup({ serverRev: 7 });
  s.stale = true;
  s.editor = true;
  await f.check();
  assert.equal(s.refreshes, 0);
  s.editor = false;
  await f.check();
  assert.equal(s.refreshes, 1);
});

test("a failed revision check is silent and does not refresh or spin", async () => {
  const { s, f } = setup({ revFails: true });
  s.clock += 60000;
  await f.check();
  assert.equal(s.refreshes, 0);
  await f.poke();
  assert.equal(s.revFetches, 1);
});

test("overlapping triggers share one check", async () => {
  const { s, f } = setup({ serverRev: 8 });
  s.clock += 60000;
  await Promise.all([f.check(), f.check(), f.check()]);
  assert.equal(s.revFetches, 1);
  assert.equal(s.refreshes, 1);
});

test("a failed refresh keeps the stale flag so the next trigger retries", async () => {
  const { s, f } = setup({ serverRev: 8 });
  let fail = true;
  const engine = { pending: () => 0, isStale: () => s.stale, noteRemoteRev: (r) => { if (r > s.knownRev) s.stale = true; } };
  const g = Freshness.create({
    engine, fetchRev: async () => 8,
    refresh: async () => { s.refreshes++; if (fail) throw new Error("boom"); s.stale = false; s.knownRev = 8; },
    editorOpen: () => false, now: () => s.clock, minGapMs: 30000,
  });
  s.clock += 60000;
  await g.check();
  assert.equal(s.refreshes, 1);
  assert.equal(s.stale, true);
  fail = false;
  await g.check();
  assert.equal(s.refreshes, 2);
  assert.equal(s.stale, false);
});


// ---- returning after being away / failed checks ---------------------------

test("a window that was away 5s+ checks even inside the debounce window", async () => {
  const { s, f } = setup({ serverRev: 8 });
  s.clock += 1000; // checked (loaded) 1s ago
  await f.check({ awayMs: 60000 });
  assert.equal(s.revFetches, 1);
  assert.equal(s.refreshes, 1);
});

test("a brief flicker (under 5s away) is still debounced", async () => {
  const { s, f } = setup({ serverRev: 8 });
  s.clock += 1000;
  await f.check({ awayMs: 2000 });
  assert.equal(s.revFetches, 0);
});

test("force bypasses the debounce (coming back online)", async () => {
  const { s, f } = setup({ serverRev: 8 });
  s.clock += 1000;
  await f.check({ force: true });
  assert.equal(s.refreshes, 1);
});

test("a failed check does not use up the debounce", async () => {
  const { s, f } = setup({ revFails: true, serverRev: 8 });
  s.clock += 60000;
  await f.check();
  assert.equal(s.revFetches, 1);
  s.revFails = false;
  await f.check(); // same clock: would be debounced if the failure had counted
  assert.equal(s.revFetches, 2);
  assert.equal(s.refreshes, 1);
});

test("after a failed check it retries at 2s then 6s, then stops", async () => {
  const { s, f } = setup({ revFails: true });
  s.clock += 60000;
  await f.check();
  assert.deepEqual(s.liveTimers().map((t) => t.ms), [2000]);
  await s.fireRetry();
  assert.equal(s.revFetches, 2);
  assert.deepEqual(s.liveTimers().map((t) => t.ms), [6000]);
  await s.fireRetry();
  assert.equal(s.revFetches, 3);
  assert.equal(s.liveTimers().length, 0, "gives up after two retries");
});

test("a retry that succeeds refreshes and stops retrying", async () => {
  const { s, f } = setup({ revFails: true, serverRev: 8 });
  s.clock += 60000;
  await f.check();
  s.revFails = false;
  await s.fireRetry();
  assert.equal(s.refreshes, 1);
  assert.equal(s.liveTimers().length, 0);
});

test("retries stop silently when the window is no longer active", async () => {
  const { s, f } = setup({ revFails: true });
  s.clock += 60000;
  await f.check();
  s.active = false;
  await s.fireRetry();
  assert.equal(s.revFetches, 1, "no request while hidden");
  assert.equal(s.liveTimers().length, 0);
});

test("no retry is scheduled when the failing window is hidden", async () => {
  const { s, f } = setup({ revFails: true, active: false });
  s.clock += 60000;
  await f.check();
  assert.equal(s.liveTimers().length, 0);
});

test("a fresh trigger cancels a pending retry and restarts the count", async () => {
  const { s, f } = setup({ revFails: true });
  s.clock += 60000;
  await f.check();
  assert.equal(s.liveTimers().length, 1);
  s.revFails = false;
  await f.check({ force: true });
  assert.equal(s.liveTimers().length, 0);
  assert.equal(s.revFetches, 2);
});


// ---- phases (what the status pill shows) ----------------------------------

test("phases: nothing changed -> checking, idle", async () => {
  const { s, f } = setup();
  s.clock += 60000;
  await f.check();
  assert.deepEqual(s.phases, ["checking", "idle"]);
});

test("phases: remote change -> checking, refreshing, idle", async () => {
  const { s, f } = setup({ serverRev: 8 });
  s.clock += 60000;
  await f.check();
  assert.deepEqual(s.phases, ["checking", "refreshing", "idle"]);
});

test("phases: a failed check says reconnecting, then recovers", async () => {
  const { s, f } = setup({ revFails: true, serverRev: 5 });
  s.clock += 60000;
  await f.check();
  assert.deepEqual(s.phases, ["checking", "retrying"]);
  s.revFails = false;
  await s.fireRetry();
  assert.deepEqual(s.phases.slice(2), ["checking", "idle"]);
});

test("phases: giving up says unreachable", async () => {
  const { s, f } = setup({ revFails: true });
  s.clock += 60000;
  await f.check();
  await s.fireRetry();
  await s.fireRetry();
  assert.equal(s.phases[s.phases.length - 1], "unreachable");
});

test("phases: a refresh held back by an open editor says waiting, then updates", async () => {
  const { s, f } = setup({ serverRev: 8, editor: true });
  s.clock += 60000;
  await f.check();
  assert.deepEqual(s.phases, ["checking", "waiting"]);
  s.editor = false;
  await f.poke();
  assert.deepEqual(s.phases.slice(2), ["refreshing", "idle"]);
});

test("phases: a failed refresh says unreachable", async () => {
  const s = { stale: true, phases: [] };
  const f = Freshness.create({
    engine: { pending: () => 0, isStale: () => s.stale, noteRemoteRev() {} },
    fetchRev: async () => 9, refresh: async () => { throw new Error("down"); },
    onPhase: (p) => s.phases.push(p), now: () => 0, timers: { setTimeout: () => 0, clearTimeout() {} },
  });
  await f.poke();
  assert.deepEqual(s.phases, ["refreshing", "unreachable"]);
});
