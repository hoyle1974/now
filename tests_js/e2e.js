// End-to-end check of the sync engine against a running server:
//   uvicorn app.main:app --port 8000 &   then   node tests_js/e2e.js
"use strict";
const assert = require("node:assert/strict");
const Sync = require("../web/sync.js");

const BASE = process.env.BASE || "http://localhost:8000";

async function realSend(req) {
  const res = await fetch(BASE + req.path, {
    method: req.method, headers: req.headers,
    body: req.body === undefined ? undefined : JSON.stringify(req.body),
  });
  const isJson = res.status !== 204 && (res.headers.get("content-type") || "").includes("json");
  return { status: res.status, body: isJson ? await res.json() : null };
}

async function fetchTree() {
  const r = await (await fetch(BASE + "/todos/tree")).json();
  return { roots: r.roots, todosById: new Map(Object.entries(r.todosById)) };
}

function makeEngine(send = realSend, store = { async load() { return []; }, async save() {} }) {
  const model = Sync.createModel();
  const notices = [];
  const engine = Sync.createEngine({
    model, store, send, refetch: fetchTree, onNotice: (n) => notices.push(n),
    timers: { setTimeout: (f) => setTimeout(f, 10), clearTimeout },
  });
  return { model, engine, notices };
}

(async () => {
  const tag = "e2e-" + Date.now();
  const { model, engine, notices } = makeEngine();

  // create, then edit the edit, then edit again — all before the network answers
  const tmp = engine.enqueue({ kind: "create", payload: { title: tag } });
  engine.enqueue({ kind: "patch", target_id: tmp, payload: { title: tag + "-b" } });
  engine.enqueue({ kind: "patch", target_id: tmp, payload: { done: true } });
  assert.equal(model.todosById.get(tmp).title, tag + "-b"); // visible instantly
  await engine.flush();
  const real = engine.resolve(tmp);
  assert.notEqual(real, tmp);
  let server = await (await fetch(`${BASE}/todos/${real}`)).json();
  assert.equal(server.title, tag + "-b");
  assert.equal(server.done, true);
  assert.equal(server.version, model.todosById.get(real).version, "client version tracks server");

  // split, then edit a child that only had a temp id when queued
  engine.enqueue({ kind: "split", target_id: real, payload: { descriptions: ["c1", "c2"] } });
  const kids = model.todosById.get(real).child_ids.slice();
  assert.ok(kids.every(Sync.isTmp));
  engine.enqueue({ kind: "patch", target_id: kids[1], payload: { title: "c2-edited" } });
  engine.enqueue({ kind: "move", target_id: kids[1], payload: { direction: "up" } });
  await engine.flush();
  server = await (await fetch(`${BASE}/todos/${real}`)).json();
  assert.equal(server.child_ids.length, 2);
  const c = await Promise.all(server.child_ids.map((id) => fetch(`${BASE}/todos/${id}`).then((r) => r.json())));
  const byOrder = c.sort((a, b) => a.order_idx - b.order_idx).map((x) => x.title);
  assert.deepEqual(byOrder, ["c2-edited", "c1"]);

  // delete then undo restores the subtree on the server
  engine.enqueue({ kind: "delete", target_id: real });
  await engine.flush();
  assert.equal((await fetch(`${BASE}/todos/${real}`)).status, 404);
  engine.enqueue({ kind: "undelete", target_id: real });
  await engine.flush();
  assert.equal((await fetch(`${BASE}/todos/${real}`)).status, 200);

  // stale write from "another device": local wins on the same field, other fields adopted
  await fetch(`${BASE}/todos/${real}`, { method: "PATCH", headers: { "content-type": "application/json" },
    body: JSON.stringify({ title: "phone title", done: false }) });
  engine.enqueue({ kind: "patch", target_id: real, payload: { title: "mac title" } });
  await engine.flush();
  server = await (await fetch(`${BASE}/todos/${real}`)).json();
  assert.equal(server.title, "mac title");
  assert.equal(server.done, false);
  assert.deepEqual(notices, []);

  // lost response: the server applies the create but the client never hears back
  let dropped = false;
  const flaky = async (req) => {
    const res = await realSend(req);
    if (req.kind !== "x" && req.method === "POST" && req.path === "/todos" && !dropped) {
      dropped = true;
      throw new Error("response lost");
    }
    return res;
  };
  const b = makeEngine(flaky);
  b.engine.enqueue({ kind: "create", payload: { title: tag + "-once" } });
  await b.engine.flush();
  await new Promise((r) => setTimeout(r, 1200)); // backoff (~0.5-1s), then retry with the same txn id
  await b.engine.flush();
  const tree = await fetchTree();
  const copies = [...tree.todosById.values()].filter((t) => t.title === tag + "-once");
  assert.equal(copies.length, 1, "retry must not duplicate");

  // cleanup
  for (const id of [real, copies[0].todo_id]) await fetch(`${BASE}/todos/${id}`, { method: "DELETE" });
  console.log("e2e ok");
})().catch((e) => { console.error(e); process.exit(1); });
