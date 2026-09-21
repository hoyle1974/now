"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const RemoteDiff = require("../web/remote-diff.js");

const tree = (...ts) => new Map(ts.map((t) => [t.id, { title: t.id, version: 1, done: false, ...t }]));
const say = (a, b) => RemoteDiff.describe(RemoteDiff.diff(RemoteDiff.snapshot(a), RemoteDiff.snapshot(b)));

test("nothing changed says nothing, collapsed alone is ignored", () => {
  assert.equal(say(tree({ id: "a" }), tree({ id: "a" })), "");
  const a = tree({ id: "a" }), b = tree({ id: "a" });
  b.get("a").collapsed = true;
  assert.equal(say(a, b), "");
});

test("one added, removed, checked off, reopened, updated", () => {
  assert.equal(say(tree(), tree({ id: "x", title: "Buy milk" })), "New from another device: “Buy milk”");
  assert.equal(say(tree({ id: "x", title: "Buy milk" }), tree()), "“Buy milk” was removed on another device");
  assert.equal(say(tree({ id: "x", title: "T" }), tree({ id: "x", title: "T", done: true, version: 2 })), "“T” was checked off on another device");
  assert.equal(say(tree({ id: "x", title: "T", done: true }), tree({ id: "x", title: "T", version: 2 })), "“T” was reopened on another device");
  assert.equal(say(tree({ id: "x", title: "T" }), tree({ id: "x", title: "T2", version: 2 })), "“T2” was updated on another device");
});

test("several changes are counted, long titles are shortened", () => {
  assert.equal(say(tree({ id: "a" }), tree({ id: "a", version: 2 }, { id: "b" }, { id: "c" })), "3 changes from another device");
  const s = say(tree(), tree({ id: "x", title: "A very long todo title that keeps going and going" }));
  assert.ok(s.includes("…") && s.length < 70);
});
