// End-to-end sharing between two users against a running server (scripts/e2e.sh):
// share → the other edits → the owner sees it → read-only refuses → unshare.
"use strict";
const assert = require("node:assert/strict");
const Sync = require("../web/sync.js");

const BASE = process.env.BASE || "http://localhost:8081";
const OWNER = "e2e@example.com";
const KID = "e2e-kid@example.com";

function as(email) {
  const headers = (extra = {}) => ({ ...extra, "X-Test-User": email });
  async function send(req) {
    const res = await fetch(BASE + req.path, {
      method: req.method, headers: headers(req.headers),
      body: req.body === undefined ? undefined : JSON.stringify(req.body),
    });
    const isJson = res.status !== 204 && (res.headers.get("content-type") || "").includes("json");
    const num = (h) => (res.headers.get(h) === null ? undefined : Number(res.headers.get(h)));
    return { status: res.status, body: isJson ? await res.json() : null, prev: num("x-rev-prev"),
      rev: num("x-rev"), partition: res.headers.get("x-partition") || undefined };
  }
  async function get(path) {
    return (await fetch(BASE + path, { headers: headers() })).json();
  }
  async function tree() {
    const r = await get("/todos/tree");
    return { roots: r.roots, todosById: new Map(Object.entries(r.todosById)), rev: r.rev, revs: r.revs,
      newShares: r.new_shares };
  }
  const model = Sync.createModel();
  const notices = [];
  const engine = Sync.createEngine({
    model, store: { async load() { return []; }, async save() {} }, send, refetch: tree,
    onNotice: (n) => notices.push(n), me: () => email,
    timers: { setTimeout: (f) => setTimeout(f, 10), clearTimeout },
  });
  const call = (method, path, body) => fetch(BASE + path, {
    method, headers: headers({ "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { model, engine, notices, tree, get, call, async reload() { engine.rebuild(await tree()); } };
}

(async () => {
  const owner = as(OWNER);
  const kid = as(KID);

  // The owner makes a list with a child.
  const tmp = owner.engine.enqueue({ kind: "create", payload: { title: "Trip", type: "list" } });
  await owner.engine.flush();
  const trip = owner.engine.resolve(tmp);
  owner.engine.enqueue({ kind: "split", target_id: trip, payload: { descriptions: ["Book hotel"] } });
  await owner.engine.flush();
  await owner.reload();
  const hotel = owner.model.todosById.get(trip).child_ids[0];

  // Share it, can edit.
  let r = await owner.call("PUT", `/todos/${trip}/share`, { mode: "rw" });
  assert.equal(r.status, 200, await r.text());
  await owner.reload();
  assert.equal(owner.model.todosById.get(trip).share_root, true);

  // The kid sees it at their root, announced.
  const kidTree = await kid.tree();
  assert.deepEqual(kidTree.newShares.map((s) => s.id), [trip]);
  kid.engine.rebuild(kidTree);
  assert.equal(kid.model.todosById.get(hotel).share.id, trip);

  // The kid checks the child off; it lands in the share with their name on it.
  const ownerRevs = owner.engine.knownRevs();
  kid.engine.enqueue({ kind: "patch", target_id: hotel, payload: { done: true } });
  await kid.engine.flush();
  const inShare = await (await fetch(`${BASE}/todos/${hotel}?share=${trip}`, { headers: { "X-Test-User": OWNER } })).json();
  assert.equal(inShare.done, true);
  assert.equal(inShare.last_edited_by, KID);

  // The owner's freshness poll notices.
  owner.engine.noteRemoteRevs((await owner.get("/todos/rev")).revs);
  assert.equal(owner.engine.isStale(), true, `revs ${JSON.stringify(ownerRevs)} should be stale`);
  await owner.reload();
  assert.equal(owner.model.todosById.get(hotel).done, true);

  // Read-only: the kid's edit is refused and dropped with a notice.
  r = await owner.call("PUT", `/todos/${trip}/share`, { mode: "ro" });
  assert.equal(r.status, 200);
  kid.engine.enqueue({ kind: "patch", target_id: hotel, payload: { title: "sneaky" } });
  await kid.engine.flush();
  assert.equal(kid.engine.pending(), 0);
  assert.match(kid.notices.at(-1).message, /read-only/);

  // Unshare: gone for the kid, an ordinary list again for the owner.
  r = await owner.call("DELETE", `/todos/${trip}/share`);
  assert.equal(r.status, 200);
  await kid.reload();
  assert.equal(kid.model.todosById.has(trip), false);
  await owner.reload();
  const back = owner.model.todosById.get(trip);
  assert.equal(back.share, null);
  assert.equal(back.child_ids[0], hotel);

  console.log("e2e sharing: ok");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
