"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Freshness = require("../web/freshness.js");

function setup({ serverRev = 5, knownRev = 5, pending = 0, editor = false, revFails = false } = {}) {
  const s = { serverRev, knownRev, pending, editor, revFails, stale: false,
    revFetches: 0, refreshes: 0, clock: 1_000_000 };
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
  });
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
