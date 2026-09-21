"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Toast = require("../web/toast.js");

function harness() {
  const classes = new Set();
  const children = [];
  const el = {
    hidden: true, onclick: null, dataset: {}, _text: "",
    classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), has: (c) => classes.has(c) },
    appendChild: (c) => children.push(c),
    set textContent(v) { this._text = v; children.length = 0; },
    get textContent() { return this._text; },
  };
  const timers = [];
  const fake = {
    setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
    clearTimeout: (id) => { if (timers[id]) timers[id].live = false; },
  };
  const toast = Toast.create(el, { timers: fake, button: () => ({}) });
  const fire = () => { const t = timers.filter((x) => x.live).pop(); t.live = false; t.fn(); };
  return { el, toast, timers, fire, children, classes };
}

test("info shows calmly and hides itself after 5s", () => {
  const h = harness();
  h.toast.show({ message: "Copied" });
  assert.equal(h.el.hidden, false);
  assert.equal(h.el.textContent, "Copied");
  assert.equal(h.classes.has("toast--calm"), true);
  assert.equal(h.timers.at(-1).ms, 5000);
  h.fire();
  assert.equal(h.el.hidden, true);
});

test("an error stays until tapped", () => {
  const h = harness();
  h.toast.show({ message: "Boom", level: "error" });
  assert.equal(h.classes.has("toast--calm"), false);
  assert.equal(h.timers.filter((t) => t.live).length, 0);
  h.el.onclick();
  assert.equal(h.el.hidden, true);
});

test("an action button runs once, hides the toast and cancels the timer", () => {
  const h = harness();
  let ran = 0;
  h.toast.show({ message: "Deleted", action: { label: "Undo", run: () => ran++ } });
  assert.equal(h.el.textContent, "Deleted · ");
  assert.equal(h.children[0].textContent, "Undo");
  h.children[0].onclick();
  assert.equal(ran, 1);
  assert.equal(h.el.hidden, true);
  assert.equal(h.timers.filter((t) => t.live).length, 0);
});

test("the latest message wins: the older timer can never hide the newer toast", () => {
  const h = harness();
  h.toast.show({ message: "one" });
  h.toast.show({ message: "two", ttl: 9000 });
  assert.equal(h.timers[0].live, false);
  assert.equal(h.el.textContent, "two");
  assert.equal(h.el.onclick, null);
});

test("hideSource and hideKind only take down their own message", () => {
  const h = harness();
  h.toast.show({ message: "api failed", level: "error", source: "api" });
  h.toast.hideSource("undo");
  assert.equal(h.el.hidden, false);
  h.toast.hideSource("api");
  assert.equal(h.el.hidden, true);
  h.toast.show({ message: "offline", level: "error", kind: "offline" });
  assert.equal(h.el.dataset.kind, "offline");
  h.toast.show({ message: "later" });
  h.toast.hideKind("offline");
  assert.equal(h.el.hidden, false);
  assert.equal("kind" in h.el.dataset, false);
});
