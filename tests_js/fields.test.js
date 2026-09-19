"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Fields = require("../web/fields.js");

const t = (id, extra = {}) => ({ todo_id: id, title: id, done: false, deleted: false,
  color: null, links: [], blocked_by: [], references: [], ...extra });
const byId = (...ts) => new Map(ts.map((x) => [x.todo_id, x]));

test("COLORS is the fixed 8-swatch palette", () => {
  assert.deepEqual(Fields.COLORS, ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"]);
});

test("isBlocked: true only while a blocker exists, is not deleted and not done", () => {
  const m = byId(t("a", { blocked_by: ["b"] }), t("b"));
  assert.equal(Fields.isBlocked(m.get("a"), m), true);
  m.get("b").done = true;
  assert.equal(Fields.isBlocked(m.get("a"), m), false);
  m.get("b").done = false; m.get("b").deleted = true;
  assert.equal(Fields.isBlocked(m.get("a"), m), false);
  assert.equal(Fields.isBlocked(t("a", { blocked_by: ["gone"] }), byId()), false);
  assert.equal(Fields.isBlocked(t("a"), byId()), false);
  assert.equal(Fields.isBlocked({ todo_id: "x" }, byId()), false);
});

test("resolveRefs skips ids missing from the model", () => {
  const m = byId(t("a"), t("b"));
  assert.deepEqual(Fields.resolveRefs(["a", "zzz", "b"], m).map((x) => x.todo_id), ["a", "b"]);
  assert.deepEqual(Fields.resolveRefs(undefined, m), []);
});

test("cleanLinks trims, drops blanks, empties labels to null, and requires http(s)", () => {
  const r = Fields.cleanLinks([
    { url: " https://a.com ", label: " A " },
    { url: "", label: "x" },
    { url: "http://b.com", label: "  " },
  ]);
  assert.deepEqual(r.links, [{ url: "https://a.com", label: "A" }, { url: "http://b.com", label: null }]);
  assert.equal(r.error, null);
  assert.ok(Fields.cleanLinks([{ url: "javascript:alert(1)", label: "" }]).error);
  assert.ok(Fields.cleanLinks([{ url: "example.com", label: "" }]).error);
  assert.ok(Fields.cleanLinks(Array.from({ length: 21 }, (_, i) => ({ url: "https://a.com/" + i }))).error);
});

test("isSafeUrl only allows http and https", () => {
  assert.equal(Fields.isSafeUrl("https://x.y/z"), true);
  assert.equal(Fields.isSafeUrl("HTTP://x.y"), true);
  assert.equal(Fields.isSafeUrl("javascript:1"), false);
  assert.equal(Fields.isSafeUrl("data:text/html,hi"), false);
  assert.equal(Fields.isSafeUrl("not a url"), false);
});

test("pickerCandidates excludes self, temp ids and deleted, filters by query, flags selected", () => {
  const m = byId(t("a", { title: "Buy milk" }), t("b", { title: "Call Bob" }),
    t("tmp:1", { title: "Buy pie" }), t("d", { title: "Buy eggs", deleted: true }));
  const all = Fields.pickerCandidates(m, "a", "", new Set(["b"]));
  assert.deepEqual(all.map((c) => c.todo.todo_id), ["b"]);
  assert.equal(all[0].selected, true);
  const q = Fields.pickerCandidates(m, "b", "BUY", new Set());
  assert.deepEqual(q.map((c) => c.todo.todo_id), ["a"]);
});

test("sameIds and changedFields compare id lists order-insensitively", () => {
  assert.equal(Fields.sameIds(["a", "b"], ["b", "a"]), true);
  assert.equal(Fields.sameIds(["a"], ["a", "b"]), false);
  const todo = t("a", { color: "red", blocked_by: ["b"], links: [{ url: "https://a.com", label: null }] });
  assert.deepEqual(Fields.changedFields(todo, { color: "red", links: [{ url: "https://a.com", label: null }],
    blocked_by: ["b"], references: [] }), {});
  assert.deepEqual(Fields.changedFields(todo, { color: null, links: todo.links, blocked_by: ["b", "c"], references: [] }),
    { color: null, blocked_by: ["b", "c"] });
});
