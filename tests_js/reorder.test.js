"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Reorder = require("../web/reorder.js");

const todo = (id, extra = {}) => ({ todo_id: id, parent_id: null, child_ids: [], order_idx: null, ...extra });

// a, b(k1, k2), c   (top level order a, b, c)
function model() {
  const nodes = [
    todo("a", { order_idx: 0 }),
    todo("b", { order_idx: 1, child_ids: ["k1", "k2"] }),
    todo("k1", { parent_id: "b", order_idx: 0 }),
    todo("k2", { parent_id: "b", order_idx: 1, child_ids: ["g"] }),
    todo("g", { parent_id: "k2", order_idx: 0 }),
    todo("c", { order_idx: 2 }),
  ];
  const todosById = new Map(nodes.map((n) => [n.todo_id, n]));
  return { todosById, roots: nodes.filter((n) => !n.parent_id) };
}

test("dropping in the middle of a row nests as its last child", () => {
  assert.deepEqual(Reorder.planDrop(model(), "a", "c", "inside"), { parent_id: "c", index: null });
});

test("before/after a row inserts among that row's siblings", () => {
  assert.deepEqual(Reorder.planDrop(model(), "c", "a", "before"), { parent_id: null, index: 0 });
  assert.deepEqual(Reorder.planDrop(model(), "a", "c", "after"), { parent_id: null, index: 2 });
  // Into another parent's children: index counts siblings without the dragged one.
  assert.deepEqual(Reorder.planDrop(model(), "a", "k1", "after"), { parent_id: "b", index: 1 });
  assert.deepEqual(Reorder.planDrop(model(), "a", "k1", "before"), { parent_id: "b", index: 0 });
});

test("moving down within the same siblings accounts for the dragged row leaving", () => {
  // a is at 0; dropping after b gives [b, a, c] -> index 1
  assert.deepEqual(Reorder.planDrop(model(), "a", "b", "after"), { parent_id: null, index: 1 });
  // c up before b: [a, c, b] -> index 1
  assert.deepEqual(Reorder.planDrop(model(), "c", "b", "before"), { parent_id: null, index: 1 });
});

test("drops that change nothing return null", () => {
  assert.equal(Reorder.planDrop(model(), "b", "a", "after"), null);   // already right after a
  assert.equal(Reorder.planDrop(model(), "b", "c", "before"), null);  // already right before c
  assert.equal(Reorder.planDrop(model(), "k2", "b", "inside"), null); // already b's last child
  assert.equal(Reorder.planDrop(model(), "a", "a", "inside"), null);
});

test("cannot drop onto the dragged row or anywhere inside its own subtree", () => {
  assert.equal(Reorder.planDrop(model(), "b", "k1", "inside"), null);
  assert.equal(Reorder.planDrop(model(), "b", "g", "before"), null);
  assert.equal(Reorder.planDrop(model(), "k2", "g", "after"), null);
});

test("unknown ids return null", () => {
  assert.equal(Reorder.planDrop(model(), "zzz", "a", "before"), null);
  assert.equal(Reorder.planDrop(model(), "a", "zzz", "before"), null);
});

test("zoneFor splits a row into before / inside / after", () => {
  const rect = { top: 100, height: 50 };
  assert.equal(Reorder.zoneFor(rect, 105), "before");
  assert.equal(Reorder.zoneFor(rect, 125), "inside");
  assert.equal(Reorder.zoneFor(rect, 145), "after");
});

// --- long-press arming ---
function fakeClock() {
  let now = 0, next = 1; const timers = new Map();
  return {
    setTimeout: (fn, ms) => { timers.set(next, { fn, at: now + ms }); return next++; },
    clearTimeout: (id) => timers.delete(id),
    advance(ms) {
      now += ms;
      for (const [id, t] of [...timers]) if (t.at <= now) { timers.delete(id); t.fn(); }
    },
  };
}

test("longPress arms after the delay if the finger stays put", () => {
  const clock = fakeClock(); let armed = 0;
  const p = Reorder.longPress(() => armed++, { delay: 350, slop: 8, ...clock });
  p.start(10, 10);
  clock.advance(349); assert.equal(armed, 0);
  p.move(12, 13);
  clock.advance(1); assert.equal(armed, 1);
  assert.equal(p.armed, true);
});

test("longPress cancels when the finger moves past the slop (a scroll)", () => {
  const clock = fakeClock(); let armed = 0;
  const p = Reorder.longPress(() => armed++, { delay: 350, slop: 8, ...clock });
  p.start(10, 10);
  clock.advance(100);
  p.move(10, 30);
  clock.advance(1000);
  assert.equal(armed, 0);
  assert.equal(p.armed, false);
});

test("longPress cancels on release before the delay", () => {
  const clock = fakeClock(); let armed = 0;
  const p = Reorder.longPress(() => armed++, { delay: 350, slop: 8, ...clock });
  p.start(0, 0); p.end(); clock.advance(1000);
  assert.equal(armed, 0);
});
