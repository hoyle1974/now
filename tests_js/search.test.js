"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Search = require("../web/search.js");

const todo = (id, title, extra = {}) => ({ todo_id: id, title, done: false, child_ids: [], parent_id: null, ...extra });
const byId = (...ts) => new Map(ts.map((t) => [t.todo_id, t]));

test("normalize lowercases and strips diacritics", () => {
  assert.equal(Search.normalize("Café Résumé"), "cafe resume");
  assert.equal(Search.normalize(undefined), "");
});

test("matches title, case-insensitive, ignoring accents", () => {
  const m = byId(todo("a", "Call Renée"), todo("b", "Buy milk"));
  assert.deepEqual(Search.search(m, "renee").map((r) => r.todo.todo_id), ["a"]);
  assert.deepEqual(Search.search(m, "MILK").map((r) => r.todo.todo_id), ["b"]);
});

test("multiple words are ANDed, in any order", () => {
  const m = byId(todo("a", "Buy oat milk"), todo("b", "Buy eggs"));
  assert.deepEqual(Search.search(m, "milk  buy").map((r) => r.todo.todo_id), ["a"]);
});

test("blank query returns nothing", () => {
  assert.deepEqual(Search.search(byId(todo("a", "x")), "   "), []);
});

test("matches link url and label, and color, tolerating missing fields", () => {
  const m = byId(
    todo("a", "Read", { links: [{ url: "https://example.com/paper", label: "Spec" }] }),
    todo("b", "Paint", { color: "Red" }),
    todo("c", "Old todo"),
    todo("d", "Null links", { links: null, color: null }),
  );
  const ids = (q) => Search.search(m, q).map((r) => r.todo.todo_id);
  assert.deepEqual(ids("example.com"), ["a"]);
  assert.deepEqual(ids("spec"), ["a"]);
  assert.deepEqual(ids("read paper"), ["a"]);
  assert.deepEqual(ids("red"), ["b"]);
  assert.deepEqual(ids("nothing"), []);
});

test("results carry breadcrumb of ancestor titles, root first", () => {
  const m = byId(
    todo("r", "Trip", { child_ids: ["m"] }),
    todo("m", "Packing", { parent_id: "r", child_ids: ["l"] }),
    todo("l", "Toothbrush", { parent_id: "m" }),
  );
  const [hit] = Search.search(m, "tooth");
  assert.deepEqual(hit.path, ["Trip", "Packing"]);
  assert.deepEqual(hit.ancestorIds, ["r", "m"]);
});

test("cyclic parents do not hang", () => {
  const m = byId(todo("a", "x", { parent_id: "b" }), todo("b", "y", { parent_id: "a" }));
  assert.equal(Search.search(m, "x").length, 1);
});

test("open items rank before done, title hits before other-field hits", () => {
  const m = byId(
    todo("d", "milk run", { done: true }),
    todo("l", "Groceries", { links: [{ url: "http://milk.example", label: "" }] }),
    todo("t", "get milk"),
  );
  assert.deepEqual(Search.search(m, "milk").map((r) => r.todo.todo_id), ["t", "l", "d"]);
});

test("matchTrashed filters flat trash items", () => {
  const items = [todo("x", "Old Idea"), todo("y", "Other")];
  assert.deepEqual(Search.matchTrashed(items, "idea").map((t) => t.todo_id), ["x"]);
  assert.deepEqual(Search.matchTrashed(null, "idea"), []);
});
