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

const sayAs = (me, a, b) => RemoteDiff.describe(RemoteDiff.diff(RemoteDiff.snapshot(a), RemoteDiff.snapshot(b)), me);

test("changes in a shared item name who made them", () => {
  const before = tree({ id: "x", title: "Book hotel", last_edited_by: "me@x.com" });
  const after = tree({ id: "x", title: "Book hotel", done: true, version: 2, last_edited_by: "alex@x.com" });
  assert.equal(sayAs("me@x.com", before, after), "alex checked off “Book hotel”");
  const renamed = tree({ id: "x", title: "Book the hotel", version: 2, last_edited_by: "alex@x.com" });
  assert.equal(sayAs("me@x.com", before, renamed), "alex updated “Book the hotel”");
  const added = tree({ id: "y", title: "Pack", last_edited_by: "alex@x.com" });
  assert.equal(sayAs("me@x.com", tree(), added), "alex added “Pack”");
});

test("a share arriving or leaving names its owner", () => {
  const share = { id: "S", owner: "sam@x.com", mode: "rw" };
  const trip = tree({ id: "S", title: "Portland trip", share, share_root: true });
  assert.equal(sayAs("me@x.com", tree(), trip), "sam shared “Portland trip” with everyone");
  assert.equal(sayAs("me@x.com", trip, tree()), "sam stopped sharing “Portland trip”");
});

test("our own edits in a share read as before", () => {
  const before = tree({ id: "x", title: "T" });
  const after = tree({ id: "x", title: "T", done: true, version: 2, last_edited_by: "me@x.com" });
  assert.equal(sayAs("me@x.com", before, after), "“T” was checked off on another device");
});
