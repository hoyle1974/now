"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Sync = require("../web/sync.js");

// ---- helpers -------------------------------------------------------------

function todo(id, extra = {}) {
  return {
    todo_id: id, title: id, done: false, create_date: "2026-01-01T00:00:00",
    due_date: null, order_idx: null, parent_id: null, child_ids: [], deleted: false,
    version: 1, ...extra,
  };
}

function treeOf(...todos) {
  const todosById = new Map(todos.map((t) => [t.todo_id, t]));
  return { roots: todos.filter((t) => !t.parent_id), todosById };
}

function memoryStore() {
  const s = { ops: [], saves: 0,
    async load() { return JSON.parse(JSON.stringify(s.ops)); },
    async save(ops) { s.saves++; s.ops = JSON.parse(JSON.stringify(ops)); } };
  return s;
}

const ok = (body, status = 200, revs = {}) => () => Promise.resolve({ status, body, ...revs });
const netFail = () => () => Promise.reject(new Error("network"));

function harness({ tree = treeOf(), script = [], refetchTree = null, saveFails = false } = {}) {
  const net = { online: true };
  const model = Sync.createModel();
  model.roots = tree.roots;
  model.todosById = tree.todosById;
  const calls = [];
  const notices = [];
  const logs = [];
  const remaps = [];
  const timers = [];
  let refetches = 0;
  let n = 0;
  const store = memoryStore();
  if (saveFails) store.save = async () => { throw new Error("quota"); };
  const engine = Sync.createEngine({
    model, store, isOnline: () => net.online,
    send: (req) => {
      calls.push(req);
      const next = script.shift();
      if (!next) throw new Error("unexpected send: " + JSON.stringify(req));
      return next(req);
    },
    refetch: async () => { refetches++; return refetchTree || treeOf(); },
    onChange() {}, onStatus() {},
    onLog: (k, d) => logs.push([k, d]),
    onNotice: (x) => notices.push(x),
    onRemap: (a, b) => remaps.push([a, b]),
    timers: {
      setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
      clearTimeout: (id) => { if (timers[id]) timers[id].live = false; },
    },
    random: () => 0.5,
    uuid: () => "u" + (++n),
  });
  const fire = () => { const t = timers.filter((x) => x.live).pop(); t.live = false; t.fn(); };
  return { net, model, engine, calls, notices, logs, remaps, timers, store, fire, get refetches() { return refetches; } };
}

// ---- 1. local application ------------------------------------------------

test("applyOp create adds a root with a temp id", () => {
  const model = Sync.createModel();
  assert.equal(Sync.applyOp(model, { kind: "create", target_id: "tmp:1", payload: { title: "a", due_date: "2026-09-20" } }), true);
  assert.equal(model.roots.length, 1);
  assert.equal(model.todosById.get("tmp:1").due_date, "2026-09-20T00:00:00");
});

test("applyOp patch sets provided fields only and clears due_date on null", () => {
  const model = Sync.createModel();
  const t = todo("a", { due_date: "2026-09-20T00:00:00" });
  Object.assign(model, treeOf(t));
  Sync.applyOp(model, { kind: "patch", target_id: "a", payload: { title: "x", due_date: null } });
  assert.equal(t.title, "x");
  assert.equal(t.due_date, null);
  assert.equal(t.done, false);
});

test("applyOp delete removes subtree and undelete restores it in place", () => {
  const model = Sync.createModel();
  const p = todo("p", { child_ids: ["c1", "c2"] });
  const c1 = todo("c1", { parent_id: "p", order_idx: 0 });
  const c2 = todo("c2", { parent_id: "p", order_idx: 1 });
  Object.assign(model, treeOf(p, c1, c2));
  Sync.applyOp(model, { kind: "delete", target_id: "c1", payload: {} });
  assert.deepEqual(p.child_ids, ["c2"]);
  assert.equal(model.todosById.has("c1"), false);
  Sync.applyOp(model, { kind: "undelete", target_id: "c1", payload: {} });
  assert.deepEqual(p.child_ids, ["c1", "c2"]);
  assert.equal(model.todosById.has("c1"), true);
});

test("applyOp split adds children with consecutive order_idx", () => {
  const model = Sync.createModel();
  const p = todo("p", { child_ids: ["c0"] });
  const c0 = todo("c0", { parent_id: "p", order_idx: 0 });
  Object.assign(model, treeOf(p, c0));
  Sync.applyOp(model, { kind: "split", target_id: "p",
    payload: { descriptions: ["a", "b"], child_tmp_ids: ["tmp:a", "tmp:b"], due_date: "2026-09-21" } });
  assert.deepEqual(p.child_ids, ["c0", "tmp:a", "tmp:b"]);
  assert.equal(model.todosById.get("tmp:a").order_idx, 1);
  assert.equal(model.todosById.get("tmp:b").order_idx, 2);
  assert.equal(model.todosById.get("tmp:b").parent_id, "p");
  assert.equal(model.todosById.get("tmp:b").due_date, "2026-09-21T00:00:00");
});

test("applyOp move swaps with neighbour and rejects edges", () => {
  const model = Sync.createModel();
  const p = todo("p", { child_ids: ["a", "b", "c"] });
  Object.assign(model, treeOf(p,
    todo("a", { parent_id: "p", order_idx: 0 }),
    todo("b", { parent_id: "p", order_idx: 1 }),
    todo("c", { parent_id: "p", order_idx: 2 })));
  assert.equal(Sync.applyOp(model, { kind: "move", target_id: "a", payload: { direction: "up" } }), false);
  assert.equal(Sync.applyOp(model, { kind: "move", target_id: "a", payload: { direction: "down" } }), true);
  assert.deepEqual(p.child_ids, ["b", "a", "c"]);
  assert.equal(model.todosById.get("a").order_idx, 1);
  assert.equal(model.todosById.get("b").order_idx, 0);
});

// ---- 2. coalescing -------------------------------------------------------

test("patches on the same target coalesce, even across other targets", async () => {
  const h = harness({ tree: treeOf(todo("a"), todo("b")), script: [] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "x" } });
  // first op immediately goes in flight (state=sending); park it by not resolving
  h.engine.enqueue({ kind: "patch", target_id: "b", payload: { done: true } });
  h.engine.enqueue({ kind: "patch", target_id: "b", payload: { title: "y" } });
  assert.equal(h.engine.pending(), 3 - 1); // a (in flight, unscripted send threw) + merged b
});

test("coalescing never touches an op that is already sending", async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const h = harness({ tree: treeOf(todo("a")), script: [
    () => gate.then(() => ({ status: 200, body: todo("a", { version: 2, done: true }) })),
    ok(todo("a", { version: 3, title: "z", done: true })),
  ] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "z" } });
  assert.equal(h.engine.pending(), 2);
  release();
  await h.engine.flush();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].headers["If-Match"], "2");
});

test("delete then undo on a not-yet-created item leaves the create intact", async () => {
  const h = harness({ script: [] });
  h.model.todosById.set("z", todo("z")); h.model.roots.push(h.model.todosById.get("z"));
  h.engine.enqueue({ kind: "patch", target_id: "z", payload: { done: true } }); // send fails, stays queued
  const id = h.engine.enqueue({ kind: "create", payload: { title: "t" } });
  const before = h.engine.pending();
  h.engine.enqueue({ kind: "delete", target_id: id });
  assert.equal(h.model.todosById.has(id), false);
  h.engine.enqueue({ kind: "undelete", target_id: id });
  assert.equal(h.engine.pending(), before);
  assert.equal(h.model.todosById.has(id), true);
});

test("undo after the create was acked still restores the item locally", async () => {
  const h = harness({ script: [ok(todo("real-1", { version: 1 })), ok({}, 204)] });
  const tmp = h.engine.enqueue({ kind: "create", payload: { title: "t" } });
  h.engine.enqueue({ kind: "delete", target_id: tmp });
  await h.engine.flush();
  assert.equal(h.model.todosById.has("real-1"), false);
  h.engine.enqueue({ kind: "undelete", target_id: tmp });
  assert.equal(h.model.todosById.has("real-1"), true);
  assert.equal(h.model.todosById.get("real-1").todo_id, "real-1");
});

test("unsent delete followed by undelete cancels both", () => {
  const h = harness({ tree: treeOf(todo("a"), todo("b")), script: [] });
  h.engine.enqueue({ kind: "patch", target_id: "b", payload: { done: true } }); // occupies the in-flight slot
  const before = h.engine.pending();
  h.engine.enqueue({ kind: "delete", target_id: "a" });
  assert.equal(h.engine.pending(), before + 1);
  h.engine.enqueue({ kind: "undelete", target_id: "a" });
  assert.equal(h.engine.pending(), before);
  assert.equal(h.model.todosById.has("a"), true);
});

// ---- 3. success, remap, chaining ----------------------------------------

test("create response remaps temp id everywhere and versions chain", async () => {
  const h = harness({ script: [
    ok(todo("real-1", { version: 1 })),
    ok(todo("real-1", { version: 2, title: "renamed" })),
    ok(todo("real-1", { version: 3, done: true })),
  ] });
  const tmp = h.engine.enqueue({ kind: "create", payload: { title: "new" } });
  h.engine.enqueue({ kind: "patch", target_id: tmp, payload: { title: "renamed" } });
  h.engine.enqueue({ kind: "patch", target_id: tmp, payload: { done: true } }); // coalesces into the rename
  await h.engine.flush();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].path, "/todos/real-1");
  assert.equal(h.calls[1].headers["If-Match"], "1");
  assert.deepEqual(h.calls[1].body, { title: "renamed", done: true });
  assert.ok(h.model.todosById.has("real-1"));
  assert.ok(!h.model.todosById.has(tmp));
  assert.equal(h.model.todosById.get("real-1").version, 2);
  assert.deepEqual(h.remaps, [[tmp, "real-1"]]);
  assert.equal(h.engine.resolve(tmp), "real-1");
});

test("remap dedupes when the real id is already in the model (replay after lost response)", async () => {
  const h = harness({ tree: treeOf(todo("real-9")), script: [ok(todo("real-9", { version: 1 }))] });
  const tmp = h.engine.enqueue({ kind: "create", payload: { title: "again" } });
  await h.engine.flush();
  assert.equal(h.model.roots.length, 1);
  assert.equal(h.model.roots[0].todo_id, "real-9");
  assert.ok(!h.model.todosById.has(tmp));
});

test("split response maps temp child ids to real ones by position", async () => {
  const h = harness({ tree: treeOf(todo("p")), script: [
    ok({
      ...todo("p", { version: 2, child_ids: ["r1", "r2"] }),
      affected: [{ todo_id: "p", version: 2 }, { todo_id: "r1", version: 1 }, { todo_id: "r2", version: 1 }],
    }),
    ok(todo("r2", { version: 2, done: true })),
  ] });
  h.engine.enqueue({ kind: "split", target_id: "p", payload: { descriptions: ["a", "b"] } });
  const tmpKids = h.model.todosById.get("p").child_ids.slice();
  h.engine.enqueue({ kind: "patch", target_id: tmpKids[1], payload: { done: true } });
  await h.engine.flush();
  assert.deepEqual(h.model.todosById.get("p").child_ids, ["r1", "r2"]);
  assert.equal(h.model.todosById.get("p").version, 2);
  assert.equal(h.calls[1].path, "/todos/r2");
  assert.equal(h.calls[1].headers["If-Match"], "1");
  assert.equal(h.model.todosById.get("r2").version, 2);
});

// ---- 5. retry ------------------------------------------------------------

test("network errors and 5xx retry with the same txn id and backoff, then succeed", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [
    netFail(), ok({}, 503), ok(todo("a", { version: 2, done: true })),
  ] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  await h.engine.flush();
  assert.equal(h.timers[0].ms, 1000 * 0.75);
  h.fire();
  await h.engine.flush();
  assert.equal(h.timers[1].ms, 2000 * 0.75);
  h.fire();
  await h.engine.flush();
  assert.equal(h.engine.pending(), 0);
  const ids = new Set(h.calls.map((c) => c.headers["X-Txn-Id"]));
  assert.equal(h.calls.length, 3);
  assert.equal(ids.size, 1);
});

test("backoff is capped at 30s", async () => {
  const script = Array.from({ length: 10 }, netFail);
  const h = harness({ tree: treeOf(todo("a")), script });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  for (let i = 0; i < 9; i++) { await h.engine.flush(); h.fire(); }
  await h.engine.flush();
  assert.equal(Math.max(...h.timers.map((t) => t.ms)), 30000 * 0.75);
});

// ---- 6/7. conflicts ------------------------------------------------------

test("409 on patch: adopt untouched server fields, keep local payload, retry with new version and txn", async () => {
  const h = harness({ tree: treeOf(todo("a", { version: 1 })), script: [
    ok(todo("a", { version: 5, title: "server title", done: true }), 409),
    ok(todo("a", { version: 6, title: "mine", done: true })),
  ] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "mine" } });
  await h.engine.flush();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].headers["If-Match"], "5");
  assert.notEqual(h.calls[1].headers["X-Txn-Id"], h.calls[0].headers["X-Txn-Id"]);
  const a = h.model.todosById.get("a");
  assert.equal(a.title, "mine");   // local wins
  assert.equal(a.done, true);      // server change adopted
  assert.equal(a.version, 6);
});

test("repeated conflicts give up after 3 with a notice", async () => {
  const conflict = () => ok(todo("a", { version: 9 }), 409);
  const h = harness({ tree: treeOf(todo("a")), script: [conflict(), conflict(), conflict(), conflict()],
    refetchTree: treeOf(todo("a", { version: 9 })) });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "x" } });
  await h.engine.flush();
  assert.equal(h.engine.pending(), 0);
  assert.ok(h.notices.some((n) => n.level === "error"));
});

test("409 on delete/split/undelete drops the op, refetches once and notifies", async () => {
  for (const kind of ["delete", "split", "undelete"]) {
    const t = todo("a", { version: 1 });
    const h = harness({ tree: treeOf(t), script: [ok(todo("a", { version: 4 }), 409)],
      refetchTree: treeOf(todo("a", { version: 4 })) });
    h.engine.enqueue({ kind, target_id: "a", payload: kind === "split" ? { descriptions: ["x"] } : {} });
    await h.engine.flush();
    assert.equal(h.engine.pending(), 0, kind);
    assert.equal(h.refetches, 1, kind);
    assert.equal(h.notices.length, 1, kind);
    assert.equal(h.model.todosById.get("a").version, 4, kind);
  }
});

// ---- 8. 404 / 4xx --------------------------------------------------------

test("404 drops all ops for the target and removes the item locally", async () => {
  const h = harness({ tree: treeOf(todo("a"), todo("b")), script: [ok({}, 404), ok(todo("b", { version: 2 }))] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "q" } });
  h.engine.enqueue({ kind: "patch", target_id: "b", payload: { done: true } });
  await h.engine.flush();
  assert.equal(h.model.todosById.has("a"), false);
  assert.equal(h.engine.pending(), 0);
  assert.equal(h.calls.length, 2);
  assert.equal(h.notices.length, 1);
});

test("422 drops the op, refetches and reports an error", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [ok({ detail: "bad" }, 422)],
    refetchTree: treeOf(todo("a")) });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "" } });
  await h.engine.flush();
  assert.equal(h.engine.pending(), 0);
  assert.equal(h.refetches, 1);
  assert.equal(h.notices[0].level, "error");
});

// ---- 9. persistence ------------------------------------------------------

test("ops persist on enqueue/ack, and load()+rebuild() replays them on a fetched tree", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [netFail()] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "unsent" } });
  await h.engine.flush();
  await h.engine.saved();
  assert.equal(h.store.ops.length, 1);

  // "reload": new engine, same store, fresh tree from the server
  const model2 = Sync.createModel();
  const engine2 = Sync.createEngine({
    model: model2, store: h.store, send: () => Promise.reject(new Error("offline")),
    refetch: async () => treeOf(), onChange() {}, onStatus() {}, onNotice() {}, onRemap() {},
    timers: { setTimeout: () => 0, clearTimeout() {} }, random: () => 0.5, uuid: () => "x",
  });
  await engine2.load();
  engine2.rebuild(treeOf(todo("a")));
  assert.equal(model2.todosById.get("a").title, "unsent");
  assert.equal(engine2.pending(), 1);
});

test("rebuild does not replay a move that may already have been applied", async () => {
  const model = Sync.createModel();
  const store = memoryStore();
  store.ops = [{ txn_id: "t", kind: "move", target_id: "a", payload: { direction: "down" },
    state: "pending", attempts: 1, conflicts: 0, sent: true }];
  const engine = Sync.createEngine({
    model, store, send: () => Promise.reject(new Error("offline")), refetch: async () => treeOf(),
    onChange() {}, onStatus() {}, onNotice() {}, onRemap() {},
    timers: { setTimeout: () => 0, clearTimeout() {} }, random: () => 0.5, uuid: () => "x",
  });
  await engine.load();
  const p = todo("p", { child_ids: ["b", "a"] });
  engine.rebuild(treeOf(p, todo("a", { parent_id: "p", order_idx: 1 }), todo("b", { parent_id: "p", order_idx: 0 })));
  assert.deepEqual(model.todosById.get("p").child_ids, ["b", "a"]);
});

test("epoch changes on enqueue and when an op leaves the outbox", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [ok(todo("a", { version: 2 }))] });
  const e0 = h.engine.epoch();
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  const e1 = h.engine.epoch();
  assert.ok(e1 > e0);
  await h.engine.flush();
  assert.ok(h.engine.epoch() > e1);
  const e2 = h.engine.epoch();
  h.engine.rebuild(treeOf(todo("a")));
  assert.equal(h.engine.epoch(), e2, "a rebuild is not a write");
});

// ---- revision tracking ---------------------------------------------------

function withRev(tree, rev) { return Object.assign(tree, { rev }); }

test("rebuild adopts the tree's revision and clears the stale flag", () => {
  const h = harness({ tree: treeOf(todo("a")) });
  assert.equal(h.engine.knownRev(), null);
  h.engine.noteRemoteRev(9);
  assert.equal(h.engine.isStale(), true);
  h.engine.rebuild(withRev(treeOf(todo("a")), 9));
  assert.equal(h.engine.knownRev(), 9);
  assert.equal(h.engine.isStale(), false);
});

test("our own consecutive writes are not a remote change", async () => {
  const h = harness({ script: [
    ok(todo("a", { version: 2 }), 200, { prev: 4, rev: 5 }),
    ok(todo("a", { version: 3 }), 200, { prev: 5, rev: 6 }),
  ] });
  h.engine.rebuild(withRev(treeOf(todo("a")), 4));
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  await h.engine.flush();
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "x" } });
  await h.engine.flush();
  assert.equal(h.engine.knownRev(), 6);
  assert.equal(h.engine.isStale(), false);
});

test("a write whose prev is ahead of what we knew means another window wrote", async () => {
  const h = harness({ script: [ok(todo("a", { version: 2 }), 200, { prev: 6, rev: 7 })] });
  h.engine.rebuild(withRev(treeOf(todo("a")), 4));
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  await h.engine.flush();
  assert.equal(h.engine.isStale(), true);
  assert.equal(h.engine.knownRev(), 7);
});

test("a 409 that reveals a newer revision marks us stale", async () => {
  const h = harness({ script: [
    ok(todo("a", { version: 5 }), 409, { prev: 8, rev: 8 }),
    ok(todo("a", { version: 6 }), 200, { prev: 8, rev: 9 }),
  ] });
  h.engine.rebuild(withRev(treeOf(todo("a")), 5));
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "x" } });
  await h.engine.flush();
  assert.equal(h.engine.isStale(), true);
});

test("a replayed response from before our known revision is ignored", async () => {
  const h = harness({ script: [ok(todo("a", { version: 2 }), 200, { prev: 4, rev: 5 })] });
  h.engine.rebuild(withRev(treeOf(todo("a")), 6));
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  await h.engine.flush();
  assert.equal(h.engine.knownRev(), 6);
  assert.equal(h.engine.isStale(), false);
});

test("noteRemoteRev only marks stale when the server is ahead", () => {
  const h = harness();
  h.engine.rebuild(withRev(treeOf(), 5));
  h.engine.noteRemoteRev(5);
  assert.equal(h.engine.isStale(), false);
  h.engine.noteRemoteRev(6);
  assert.equal(h.engine.isStale(), true);
});

test("without a known revision (first load failed) we treat the server as ahead", () => {
  const h = harness();
  h.engine.noteRemoteRev(0);
  assert.equal(h.engine.isStale(), true);
});


// ---- event log hooks -------------------------------------------------------

const kinds = (h) => h.logs.map(([k]) => k);

test("logs enqueue and send, without leaking titles", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [ok(todo("a", { version: 2 }), 200, { prev: 1, rev: 2 })] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "secret title" } });
  await h.engine.flush();
  assert.deepEqual(kinds(h), ["enqueue", "send"]);
  assert.match(h.logs[1][1], /patch 200/);
  assert.match(h.logs[1][1], /rev 1->2/);
  assert.ok(!JSON.stringify(h.logs).includes("secret title"));
});

test("logs a failed send and the backoff", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [netFail()] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  await h.engine.flush();
  assert.deepEqual(kinds(h), ["enqueue", "send-fail", "backoff"]);
  assert.match(h.logs[1][1], /network/);
  assert.match(h.logs[2][1], /750ms.*attempt 1/);
});

test("logs a 409 conflict and the remote write it reveals", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [
    ok(todo("a", { version: 5 }), 409, { prev: 8, rev: 8 }),
    ok(todo("a", { version: 6 }), 200, { prev: 8, rev: 9 }),
  ] });
  h.engine.rebuild(Object.assign(treeOf(todo("a")), { rev: 5 }));
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { title: "x" } });
  await h.engine.flush();
  assert.ok(kinds(h).includes("conflict"));
  assert.ok(kinds(h).includes("stale"));
  assert.match(h.logs.find(([k]) => k === "stale")[1], /prev 8 > known 5/);
});

test("logs a rebuild with the revision and counts", () => {
  const h = harness();
  h.engine.rebuild(Object.assign(treeOf(todo("a"), todo("b")), { rev: 12 }));
  assert.equal(h.logs.at(-1)[0], "rebuild");
  assert.match(h.logs.at(-1)[1], /rev 12.*2 todos.*0 pending/);
});

test("logs dropped ops (404 / permanent failure)", async () => {
  const h = harness({ tree: treeOf(todo("a")), script: [ok({}, 404)] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { done: true } });
  await h.engine.flush();
  assert.ok(kinds(h).includes("drop"));
});

test("collapsed patch applies optimistically and is sent without If-Match", async () => {
  const h = harness({ tree: treeOf(todo("a", { version: 4 })), script: [
    ok(todo("a", { version: 4, collapsed: true })),
  ] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { collapsed: true } });
  assert.equal(h.model.todosById.get("a").collapsed, true);
  await h.engine.flush();
  assert.deepEqual(h.calls[0].body, { collapsed: true });
  assert.equal(h.calls[0].headers["If-Match"], undefined);
});

test("collapsed mixed with a content edit stays conditional", async () => {
  const h = harness({ tree: treeOf(todo("a", { version: 4 })), script: [
    ok(todo("a", { version: 5, done: true, collapsed: true })),
  ] });
  h.engine.enqueue({ kind: "patch", target_id: "a", payload: { collapsed: true, done: true } });
  await h.engine.flush();
  assert.deepEqual(h.calls[0].body, { collapsed: true, done: true });
  assert.equal(h.calls[0].headers["If-Match"], "4");
});

// ---- roots, remap holes, storage failure, offline -----------------------

test("applyOp move reorders roots too", () => {
  const t = treeOf(todo("a"), todo("b"), todo("c"));
  const model = Sync.createModel();
  model.roots = t.roots; model.todosById = t.todosById;
  assert.equal(Sync.applyOp(model, { kind: "move", target_id: "c", payload: { direction: "up" } }), true);
  assert.deepEqual(model.roots.map((r) => r.todo_id), ["a", "c", "b"]);
  assert.equal(Sync.applyOp(model, { kind: "move", target_id: "a", payload: { direction: "up" } }), false);
});

test("remap fixes undo snapshots that reference the temp id", async () => {
  const h = harness({ script: [ok({ todo_id: "real1", version: 1, create_date: "x", order_idx: 0 })] });
  h.net.online = false;
  const tmp = h.engine.enqueue({ kind: "create", payload: { title: "p" } });
  h.engine.enqueue({ kind: "split", target_id: tmp, payload: { descriptions: ["c"] } });
  const child = h.model.todosById.get(tmp).child_ids[0];
  h.engine.enqueue({ kind: "delete", target_id: child });      // snapshot whose parent is tmp
  const snap = h.model.trash.get(child);
  assert.equal(snap.parent_id, tmp);
  h.net.online = true;
  h.engine.kick();
  await h.engine.flush();
  assert.equal(snap.parent_id, "real1");
});

test("a save failure is reported once and cleared when a save succeeds", async () => {
  const h = harness({ saveFails: true });
  h.net.online = false;
  h.engine.enqueue({ kind: "create", payload: { title: "x" } });
  await h.engine.saved();
  assert.equal(h.engine.status().unsaved, true);
  assert.equal(h.notices.filter((n) => n.level === "error").length, 1);
  h.engine.enqueue({ kind: "create", payload: { title: "y" } });
  await h.engine.saved();
  assert.equal(h.notices.filter((n) => n.level === "error").length, 1);
  h.store.save = async () => {};
  h.engine.enqueue({ kind: "create", payload: { title: "z" } });
  await h.engine.saved();
  assert.equal(h.engine.status().unsaved, false);
});

test("offline: nothing is sent and no retry timer runs until kicked online", async () => {
  const h = harness({ script: [ok({ todo_id: "r", version: 1, create_date: "x", order_idx: 0 })] });
  h.net.online = false;
  h.engine.enqueue({ kind: "create", payload: { title: "x" } });
  await h.engine.flush();
  assert.equal(h.calls.length, 0);
  assert.equal(h.timers.length, 0);
  assert.equal(h.engine.status().state, "offline");
  h.net.online = true;
  h.engine.kick();
  await h.engine.flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.engine.status().state, "synced");
});

test("kick(true) sends even when the device claims to be offline", async () => {
  const h = harness({ script: [ok({ todo_id: "r", version: 1, create_date: "x", order_idx: 0 })] });
  h.net.online = false;
  h.engine.enqueue({ kind: "create", payload: { title: "x" } });
  h.engine.kick(true);
  await h.engine.flush();
  assert.equal(h.calls.length, 1);
});
