"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
require("../web/mascot.js");
const { armOnFirstTap } = globalThis.Mascot.shake;

const storage = (v) => ({ getItem: () => v, setItem() {}, removeItem() {} });
const doc = () => {
  const d = { listeners: [], addEventListener(type, fn, opts) { d.listeners.push({ type, fn, opts }); } };
  return d;
};

test("does nothing when shake was never turned on", () => {
  const d = doc();
  assert.equal(armOnFirstTap(d, storage(null), async () => "granted"), false);
  assert.equal(d.listeners.length, 0);
});

test("re-arms on the first tap only, once", async () => {
  const d = doc();
  let calls = 0;
  assert.equal(armOnFirstTap(d, storage("1"), async () => { calls++; return "granted"; }), true);
  assert.equal(d.listeners.length, 1);
  assert.equal(d.listeners[0].type, "pointerup");
  assert.equal(d.listeners[0].opts.once, true);
  assert.equal(calls, 0, "nothing happens until a tap");
  await d.listeners[0].fn();
  assert.equal(calls, 1);
});

test("survives storage that throws", () => {
  const bad = { getItem() { throw new Error("blocked"); } };
  assert.equal(armOnFirstTap(doc(), bad, async () => "granted"), false);
});
