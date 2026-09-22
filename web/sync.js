// Optimistic-edit sync engine: a local model, an ordered outbox of ops, and a
// single-flight loop that sends them with retry, idempotency and version
// checks. No DOM access, so it runs unchanged under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./types.js"));
  } else {
    root.Sync = factory(root.Types);
  }
})(typeof self !== "undefined" ? self : this, function (Types) {
  "use strict";

  const MAX_CONFLICTS = 3;
  const BACKOFF_BASE_MS = 1000;
  const BACKOFF_CAP_MS = 30000;
  // Older than this, a sent create/split may be committed server-side but unacked
  // while the server's 30-day replay log is about to forget it.
  const SUSPECT_AGE_MS = 25 * 24 * 3600 * 1000;
  const PATCH_FIELDS = ["title", "done", "due_date", "collapsed", "repeat",
    "color", "links", "blocked_by", "references", "type"];

  // Fields holding lists of todo ids, which can hold a temporary id.
  const LINK_FIELDS = ["blocked_by", "references"];
  function remapList(list, tmp, real) {
    if (!Array.isArray(list)) return;
    for (let i = 0; i < list.length; i++) if (list[i] === tmp) list[i] = real;
  }

  const isTmp = (id) => typeof id === "string" && id.startsWith("tmp:");

  // The server stores naive local datetimes, and the UI parses them as local
  // time. A bare "YYYY-MM-DD" from a date input would parse as UTC in JS and
  // land on the previous day in western timezones, so give it a time part.
  function normalizeDue(value) {
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
      return value + "T00:00:00";
    }
    return value ?? null;
  }

  function defaultUuid() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  // ---- model ------------------------------------------------------------

  function createModel() {
    // roots hold the same objects as todosById; trash keeps deleted subtrees
    // so an undo can put them back without a server round trip.
    return { roots: [], todosById: new Map(), trash: new Map() };
  }

  function newNode(id, title, dueDate, parentId, orderIdx, type = "todo") {
    return {
      todo_id: id, title, done: false, create_date: new Date().toISOString(),
      due_date: normalizeDue(dueDate), order_idx: orderIdx, parent_id: parentId,
      child_ids: [], deleted: false, collapsed: false, repeat: null, spawned_id: null, version: 0,
      color: null, type, links: [], blocked_by: [], references: [],
    };
  }

  function subtreeNodes(model, id) {
    const out = [];
    const walk = (nodeId) => {
      const node = model.todosById.get(nodeId);
      if (!node) return;
      out.push(node);
      node.child_ids.forEach(walk);
    };
    walk(id);
    return out;
  }

  // Detach a node from its parent's child_ids (or from roots); returns the
  // index it occupied.
  function detach(model, node) {
    const list = node.parent_id ? model.todosById.get(node.parent_id)?.child_ids : null;
    if (list) {
      const i = list.indexOf(node.todo_id);
      if (i >= 0) list.splice(i, 1);
      return i;
    }
    const i = model.roots.indexOf(node);
    if (i >= 0) model.roots.splice(i, 1);
    return i;
  }

  function sortedSiblings(model, parent) {
    return parent.child_ids
      .map((id) => model.todosById.get(id))
      .filter(Boolean)
      .sort((a, b) => (a.order_idx ?? 999999) - (b.order_idx ?? 999999));
  }

  function sortedRoots(model) {
    return model.roots.slice().sort((a, b) => (a.order_idx ?? 999999) - (b.order_idx ?? 999999));
  }

  // Ids "Clear completed" would delete: done todos whose whole subtree is done.
  // Only the topmost of each such subtree (it takes its descendants with it),
  // mirroring the server (db_firestore.clear_completed).
  function clearableIds(model) {
    const memo = new Map();
    // [everything beneath is done, a todo is here or beneath]; a container's own done means nothing.
    const check = (node) => {
      if (!memo.has(node.todo_id)) {
        memo.set(node.todo_id, [false, false]);
        const kids = node.child_ids.map((c) => model.todosById.get(c)).filter(Boolean).map(check);
        const hasState = Types.can(node, "hasCheckbox");
        memo.set(node.todo_id, [kids.every((k) => k[0]) && (!!node.done || !hasState),
                                hasState || kids.some((k) => k[1])]);
      }
      return memo.get(node.todo_id);
    };
    const out = [];
    const pending = model.roots.slice();
    while (pending.length) {
      const node = pending.pop();
      const [allDone, hasTodo] = check(node);
      if (allDone && hasTodo) out.push(node.todo_id);
      else node.child_ids.forEach((c) => { const n = model.todosById.get(c); if (n) pending.push(n); });
    }
    return out;
  }

  // ---- ops --------------------------------------------------------------
  // One entry per op kind: everything about it in one place. To add an op, add an entry.
  //   apply(model, op)          optimistic local effect; false = can't apply (target gone, ...)
  //   request(op)               { method, path, body? } for the wire (headers are added around it)
  //   versioned                 true, or (op) => bool: send If-Match with the target's version
  //   ack(op, body, ctx)        after a 2xx: adopt the server's ids/versions. ctx: { model, remapId, nodeOf }
  //   retryOn409                a version conflict is retried with the server's version, local wins
  //   onConflict(node, op, body)  patch only: adopt fields we did not edit before the retry
  //   reloadAfterAck            reload the tree after the ack (the server made things we can't derive)
  //   on400 / on404             { log, notice? }: drop the op and reload instead of the generic handling
  //   mintsTarget               enqueue mints a temporary target id (create)
  //   mayCommitUnacked          a very old sent op may already be committed (create, split); then
  //   alreadyCommitted(op, todosById, fresh)  says whether the server tree already holds it
  //   prepare(op, uuid)         fill in payload ids at enqueue time
  //   coalesce(prev, op)        "merge" (prev absorbed op), "cancel" (op and prev cancel out) or null
  //   queueEvenIfUnapplied      keep the op although apply() said no (undelete of an already-restored item)
  const OPS = {
    create: {
      mintsTarget: true,
      mayCommitUnacked: true,
      alreadyCommitted(op, todosById, fresh) {
        for (const t of todosById.values()) {
          if (!t.parent_id && t.title === op.payload.title && fresh(t)) return true;
        }
        return false;
      },
      apply(model, { target_id: id, payload = {} }) {
        if (model.todosById.has(id)) return false;
        const node = newNode(id, payload.title, payload.due_date, null, null, payload.type);
        if (payload.color) node.color = payload.color;
        model.todosById.set(id, node);
        model.roots.push(node);
        return true;
      },
      request({ payload: p = {} }) {
        const body = { title: p.title };
        if (p.color) body.color = p.color;
        if (p.due_date) body.due_date = p.due_date;
        if (p.type) body.type = p.type;
        return { method: "POST", path: "/todos", body };
      },
      ack(op, body, { model, remapId }) {
        if (!body || !body.todo_id) throw new Error("create reply had no todo_id");
        remapId(op.target_id, body.todo_id);
        const node = model.todosById.get(body.todo_id);
        if (node) Object.assign(node, { version: body.version, create_date: body.create_date, order_idx: body.order_idx });
      },
    },
    patch: {
      retryOn409: true,
      // Collapsing is view state: last write wins, so it carries no version.
      versioned: (op) => Object.keys(patchBody(op.payload || {})).some((f) => f !== "collapsed"),
      apply(model, { target_id: id, payload = {} }) {
        const node = model.todosById.get(id);
        if (!node) return false;
        for (const f of PATCH_FIELDS) {
          if (f in payload) node[f] = f === "due_date" ? normalizeDue(payload[f]) : payload[f];
        }
        return true;
      },
      request(op) {
        return { method: "PATCH", path: `/todos/${op.target_id}`, body: patchBody(op.payload || {}) };
      },
      ack: ackVersion,
      onConflict(node, op, body) {
        for (const f of PATCH_FIELDS) {
          if (!(f in op.payload) && f in body) node[f] = f === "due_date" ? normalizeDue(body[f]) : body[f];
        }
      },
      coalesce(prev, op) {
        if (prev.kind !== "patch") return null;
        Object.assign(prev.payload, op.payload);
        return "merge";
      },
    },
    delete: {
      versioned: true,
      apply(model, { target_id: id }) {
        const node = model.todosById.get(id);
        if (!node) return false;
        const nodes = subtreeNodes(model, id);
        const index = detach(model, node);
        model.trash.set(id, { nodes, parent_id: node.parent_id, index });
        nodes.forEach((n) => model.todosById.delete(n.todo_id));
        return true;
      },
      request: (op) => ({ method: "DELETE", path: `/todos/${op.target_id}` }),
    },
    clear_completed: {
      apply(model) {
        const ids = clearableIds(model);
        if (!ids.length) return false;
        ids.forEach((cid) => OPS.delete.apply(model, { target_id: cid }));
        return true;
      },
      request: () => ({ method: "POST", path: "/todos/clear-completed" }),
    },
    undelete: {
      queueEvenIfUnapplied: true,
      // Undo of a delete we just made: nothing to be stale against, so not versioned.
      apply(model, { target_id: id }) {
        const snap = model.trash.get(id);
        if (!snap) return false;
        model.trash.delete(id);
        snap.nodes.forEach((n) => model.todosById.set(n.todo_id, n));
        const node = snap.nodes[0];
        // The server resets a missing/trashed parent to null; mirror that so
        // later moves and detaches look in the roots list.
        if (!(snap.parent_id && model.todosById.get(snap.parent_id))) node.parent_id = null;
        const parent = snap.parent_id ? model.todosById.get(snap.parent_id) : null;
        const list = parent ? parent.child_ids : model.roots;
        const item = parent ? id : node;
        list.splice(Math.min(Math.max(snap.index, 0), list.length), 0, item);
        return true;
      },
      request: (op) => ({ method: "PATCH", path: `/todos/${op.target_id}/undelete` }),
      ack(op, body, { model }) {
        for (const a of (body && body.affected) || []) {
          const node = model.todosById.get(a.todo_id);
          if (node) node.version = a.version;
        }
      },
      coalesce(prev) {
        return prev.kind === "delete" ? "cancel" : null;
      },
    },
    split: {
      versioned: true,
      mayCommitUnacked: true,
      alreadyCommitted(op, todosById, fresh) {
        const parent = todosById.get(op.target_id);
        if (!parent) return false;
        const kids = parent.child_ids.map((c) => todosById.get(c)).filter((c) => c && fresh(c));
        return op.payload.descriptions.every((d) => kids.some((k) => k.title === d));
      },
      prepare(op, uuid) {
        if (!op.payload.child_tmp_ids) op.payload.child_tmp_ids = op.payload.descriptions.map(() => "tmp:" + uuid());
      },
      apply(model, { target_id: id, payload = {} }) {
        const parent = model.todosById.get(id);
        if (!parent) return false;
        const tmpIds = payload.child_tmp_ids || [];
        let next = Math.max(-1, ...parent.child_ids.map((c) => model.todosById.get(c)?.order_idx ?? -1)) + 1;
        payload.descriptions.forEach((title, i) => {
          if (model.todosById.has(tmpIds[i])) return;
          const child = newNode(tmpIds[i], title, payload.due_date, id, next++, payload.type);
          model.todosById.set(child.todo_id, child);
          parent.child_ids.push(child.todo_id);
        });
        return true;
      },
      request({ target_id: id, payload: p = {} }) {
        const body = { descriptions: p.descriptions };
        if (p.due_date) body.due_date = p.due_date;
        if (p.type) body.type = p.type;
        return { method: "POST", path: `/todos/${id}/split`, body };
      },
      ack(op, body, { model, remapId }) {
        const aff = (body && body.affected) || [];
        const parent = model.todosById.get(op.target_id);
        if (parent && aff[0]) parent.version = aff[0].version;
        (op.payload.child_tmp_ids || []).forEach((tmp, i) => {
          if (!aff[i + 1]) return;
          remapId(tmp, aff[i + 1].todo_id);
          const child = model.todosById.get(aff[i + 1].todo_id);
          if (child) child.version = aff[i + 1].version;
        });
      },
    },
    move: {
      versioned: true,
      retryOn409: true,
      apply(model, { target_id: id, payload = {} }) {
        const node = model.todosById.get(id);
        if (!node) return false;
        const parent = node.parent_id ? model.todosById.get(node.parent_id) : null;
        if (node.parent_id && !parent) return false;
        const sibs = parent ? sortedSiblings(model, parent) : sortedRoots(model);
        if (sibs.length < 2) return false;
        const pos = sibs.indexOf(node);
        const to = payload.direction === "up" ? pos - 1 : pos + 1;
        if (to < 0 || to >= sibs.length) return false;
        sibs.splice(pos, 1);
        sibs.splice(to, 0, node);
        sibs.forEach((s, i) => { s.order_idx = i; });
        if (parent) parent.child_ids = sibs.map((s) => s.todo_id);
        else model.roots = sibs;
        return true;
      },
      request: (op) => ({ method: "PATCH", path: `/todos/${op.target_id}/move/${op.payload.direction}` }),
      ack: ackVersion,
    },
    repeat: {
      // Not versioned: the server spawns at most once per todo, whatever its version.
      reloadAfterAck: true, // the new occurrence (a whole subtree with server ids) exists only there
      // The rule was cleared on another device: nothing to spawn.
      on400: { log: "repeat: 400, no longer repeating; reloading" },
      apply(model, { target_id: id }) {
        // The copy is made by the server; locally we only remember that this
        // todo is already spawning, so completing it again queues nothing.
        const node = model.todosById.get(id);
        if (!node) return false;
        if (!node.spawned_id) node.spawned_id = "pending";
        return true;
      },
      request: (op) => ({ method: "POST", path: `/todos/${op.target_id}/repeat`, body: { today: op.payload.today } }),
    },
    reparent: {
      versioned: true,
      retryOn409: true,
      // Either the todo or its new parent is gone; the local model can't tell
      // which, so reload rather than guess.
      on404: { log: "reparent: 404, reloading from the server", notice: "Couldn't move that; reloaded." },
      apply(model, { target_id: id, payload = {} }) {
        const node = model.todosById.get(id);
        if (!node) return false;
        const newParentId = payload.parent_id ?? null;
        const newParent = newParentId === null ? null : model.todosById.get(newParentId);
        if (newParentId !== null && !newParent) return false;
        // Moving a todo into its own subtree would orphan it.
        if (newParentId !== null && subtreeNodes(model, id).some((n) => n.todo_id === newParentId)) return false;
        detach(model, node);
        const sibs = (newParent ? sortedSiblings(model, newParent) : sortedRoots(model)).filter((s) => s !== node);
        const at = payload.index == null ? sibs.length : Math.max(0, Math.min(payload.index, sibs.length));
        sibs.splice(at, 0, node);
        sibs.forEach((s, i) => { s.order_idx = i; });
        node.parent_id = newParentId;
        if (newParent) newParent.child_ids = sibs.map((s) => s.todo_id);
        else model.roots = sibs;
        return true;
      },
      request: (op) => ({
        method: "PATCH", path: `/todos/${op.target_id}/reparent`,
        body: { parent_id: op.payload.parent_id ?? null, index: op.payload.index ?? null },
      }),
      ack: ackVersion,
    },
  };

  function patchBody(payload) {
    const body = {};
    for (const f of PATCH_FIELDS) if (f in payload) body[f] = payload[f];
    return body;
  }

  // 2xx for an op that only moves the target's version forward.
  function ackVersion(op, body, { nodeOf }) {
    const node = nodeOf(op.target_id);
    if (node && body) node.version = body.version;
  }

  // Apply an op to the local model. Returns false when it can't apply
  // (unknown target, move off the end of the list, ...).
  function applyOp(model, op) {
    const spec = OPS[op.kind];
    return spec ? spec.apply(model, op) : false;
  }

  // ---- requests ---------------------------------------------------------

  function buildRequest(op, version) {
    const spec = OPS[op.kind];
    if (!spec) throw new Error("unknown op kind " + op.kind);
    const headers = { "Content-Type": "application/json", "X-Txn-Id": op.txn_id };
    const versioned = typeof spec.versioned === "function" ? spec.versioned(op) : Boolean(spec.versioned);
    if (versioned && version != null && version > 0) headers["If-Match"] = String(version);
    return { ...spec.request(op), headers };
  }

  // ---- engine -----------------------------------------------------------

  function createEngine(opts) {
    const { model, store, send, refetch } = opts;
    const onChange = opts.onChange || (() => {});
    const onStatus = opts.onStatus || (() => {});
    const onNotice = opts.onNotice || (() => {});
    const onRemap = opts.onRemap || (() => {});
    // Diagnostics only (kind, short detail); never receives todo titles.
    const log = opts.onLog || (() => {});
    const timers = opts.timers || { setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (t) => clearTimeout(t) };
    const random = opts.random || Math.random;
    const uuid = opts.uuid || defaultUuid;
    const now = opts.now || Date.now;
    // navigator.onLine can't be trusted to say "yes", but a "no" is reliable
    // enough to stop burning retries; a manual kick(true) overrides it.
    const isOnline = opts.isOnline || (() => true);

    let ops = [];
    const aliases = new Map();
    let running = false;
    let backoffTimer = null;
    let lastError = false;
    // Bumped on every enqueue and every op that leaves the outbox, so a caller
    // can tell whether anything changed while it was awaiting a tree fetch.
    let epoch = 0;
    // The server's change counter as we last saw it, and whether we've learned
    // that another window has written since (see observeRev / noteRemoteRev).
    let knownRev = null;
    let stale = false;
    // True while the outbox can't be written to device storage: edits still
    // sync, but would be lost if the page were closed first.
    let saveFailed = false;
    // The server refused our credentials (401/403) or we have none: edits are
    // kept and retried, and the status says so.
    let authBlocked = false;
    // Holding the outbox because the device is offline (no retry timer runs).
    let parked = false;
    let forceOnline = false;
    // A restored outbox must not replay against an empty model (no versions, so
    // no If-Match): hold sending until a server tree has been loaded.
    let needTree = false;
    let saveChain = Promise.resolve();
    const waiters = [];

    // -- persistence / status
    function persist() {
      const snapshot = JSON.parse(JSON.stringify(ops));
      saveChain = saveChain.then(() => store.save(snapshot)).then(() => {
        if (saveFailed) {
          saveFailed = false;
          emitStatus();
        }
      }, (e) => {
        log("save-fail", e && e.message ? e.message : String(e));
        if (!saveFailed) {
          saveFailed = true;
          notice("error", "Couldn't save your edits on this device. Keep this page open until they sync.");
        }
        emitStatus();
      });
      return saveChain;
    }

    function status() {
      let state = "synced";
      if (backoffTimer !== null || parked) state = "offline";
      else if (ops.length) state = "syncing";
      else if (lastError) state = "error";
      return { state, pending: ops.length, unsaved: saveFailed && ops.length > 0,
        auth: authBlocked && ops.length > 0 };
    }

    function emitStatus() { onStatus(status()); }

    function settleIfIdle() {
      if (!running && (ops.length === 0 || backoffTimer !== null || parked)) {
        waiters.splice(0).forEach((resolve) => resolve());
      }
    }

    // -- revision tracking
    // Every write response says which revision it started from (prev) and where
    // it ended (rev). If prev is ahead of what we knew, another window wrote in
    // between. A prev below what we know is a replayed answer to a request we
    // already accounted for.
    function observeRev(prev, rev) {
      if (prev == null || rev == null) return;
      if (knownRev !== null && prev > knownRev) {
        stale = true;
        log("stale", `remote write detected: prev ${prev} > known ${knownRev}`);
      }
      if (knownRev === null || rev > knownRev) knownRev = rev;
    }

    // Result of the cheap /todos/rev poll. Deliberately leaves knownRev alone:
    // it only moves when we actually load the newer tree.
    function noteRemoteRev(rev) {
      if (knownRev === null || rev > knownRev) stale = true;
    }

    // -- ids
    function resolve(id) {
      let cur = id;
      while (aliases.has(cur)) cur = aliases.get(cur);
      return cur;
    }

    function remapId(tmp, real) {
      aliases.set(tmp, real);
      for (const op of ops) {
        if (op.target_id === tmp) op.target_id = real;
        if (op.payload && op.payload.parent_id === tmp) op.payload.parent_id = real;
        for (const f of LINK_FIELDS) remapList(op.payload && op.payload[f], tmp, real);
      }
      for (const n of model.todosById.values()) {
        for (const f of LINK_FIELDS) remapList(n[f], tmp, real);
      }

      // Undo snapshots can hold the temporary id in several places: as their own
      // key, as a member, as a member's parent or child, or as the parent the
      // snapshot would be restored under.
      const trashed = model.trash.get(tmp);
      if (trashed) {
        model.trash.delete(tmp);
        model.trash.set(real, trashed);
      }
      for (const snap of model.trash.values()) {
        if (snap.parent_id === tmp) snap.parent_id = real;
        for (const n of snap.nodes) {
          for (const f of LINK_FIELDS) remapList(n[f], tmp, real);
          if (n.todo_id === tmp) n.todo_id = real;
          if (n.parent_id === tmp) n.parent_id = real;
          n.child_ids = n.child_ids.map((c) => (c === tmp ? real : c));
        }
      }
      const node = model.todosById.get(tmp);
      if (node) {
        const existing = model.todosById.get(real);
        if (existing) {
          // The real node is already here (replay after a lost response):
          // keep it and fold the temporary one into it.
          for (const c of node.child_ids) {
            const child = model.todosById.get(c);
            if (child) child.parent_id = real;
            if (!existing.child_ids.includes(c)) existing.child_ids.push(c);
          }
          detach(model, node);
          model.todosById.delete(tmp);
        } else {
          const list = node.parent_id ? model.todosById.get(node.parent_id)?.child_ids : null;
          const at = list ? list.indexOf(tmp) : -1;
          if (at >= 0) list[at] = real;
          model.todosById.delete(tmp);
          node.todo_id = real;
          model.todosById.set(real, node);
          for (const c of node.child_ids) {
            const child = model.todosById.get(c);
            if (child) child.parent_id = real;
          }
        }
      }
      onRemap(tmp, real);
    }

    // -- enqueue and coalesce
    function removeOps(predicate) {
      ops = ops.filter((o) => !predicate(o));
      epoch += 1;
    }

    function tryCoalesce(op) {
      // Only the *most recent* op on this target is a coalesce candidate: ops on one
      // target must apply in queue order, so merging past an earlier, non-coalescable
      // op (e.g. a delete) would reorder its effect relative to what's in between.
      for (let i = ops.length - 1; i >= 0; i--) {
        const prev = ops[i];
        if (prev.target_id !== op.target_id) continue;
        // A sent op may already be on the server (lost response, restored
        // outbox) and would replay its logged answer under the same txn_id, so
        // a merged change would never apply. Queue a new op instead.
        if (prev.state !== "pending" || prev.sent) return false;
        const result = OPS[op.kind].coalesce && OPS[op.kind].coalesce(prev, op);
        if (result === "cancel") ops.splice(i, 1);
        if (result) return true;
        return false;
      }
      return false;
    }

    // Returns the target id (the new temp id for a create), or false if the
    // op can't apply locally.
    function enqueue({ kind, target_id, payload = {} }) {
      const op = {
        txn_id: uuid(), kind,
        target_id: OPS[kind]?.mintsTarget ? "tmp:" + uuid() : resolve(target_id),
        payload: { ...payload }, state: "pending", attempts: 0, conflicts: 0, sent: false, queued_at: now(),
      };
      // Callers may still hold a temporary id whose create has since been acked.
      if (op.payload.parent_id) op.payload.parent_id = resolve(op.payload.parent_id);
      for (const f of LINK_FIELDS) {
        if (Array.isArray(op.payload[f])) op.payload[f] = op.payload[f].map(resolve);
      }
      if (OPS[kind] && OPS[kind].prepare) OPS[kind].prepare(op, uuid);
      const applied = applyOp(model, op);
      if (!applied && !(OPS[kind] && OPS[kind].queueEvenIfUnapplied)) return false;
      const merged = tryCoalesce(op);
      if (!merged) ops.push(op);
      log("enqueue", `${kind}${merged ? " (merged)" : ""}, ${ops.length} pending`);
      epoch += 1;
      persist();
      onChange();
      emitStatus();
      run();
      return op.target_id;
    }

    // -- sync loop
    function backoffDelay(attempts) {
      const base = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** (attempts - 1));
      return base * (0.5 + random() * 0.5);
    }

    function scheduleRetry(op) {
      op.attempts += 1;
      op.state = "pending";
      const delay = backoffDelay(op.attempts);
      log("backoff", `${Math.round(delay)}ms, attempt ${op.attempts}`);
      backoffTimer = timers.setTimeout(() => {
        backoffTimer = null;
        run();
      }, delay);
      persist();
      emitStatus();
    }

    function dropHead(op) {
      const i = ops.indexOf(op);
      if (i >= 0) ops.splice(i, 1);
      epoch += 1;
      persist();
    }

    function notice(level, message) {
      onNotice({ level, message });
    }

    async function refetchAndRebuild() {
      try {
        rebuild(await refetch());
      } catch (e) {
        // Offline: keep the local view; the next successful fetch reconciles.
      }
    }

    // A deleted node lives in the undo snapshot until the delete is acked; its
    // version must still follow earlier acks and be sent as If-Match.
    function nodeOf(id) {
      return model.todosById.get(id) || (model.trash.get(id)?.nodes[0]);
    }

    function ackSuccess(op, body) {
      lastError = false;
      authBlocked = false;
      const spec = OPS[op.kind];
      if (spec && spec.ack) spec.ack(op, body, { model, remapId, nodeOf });
    }

    async function handle(op, res) {
      const { status: code, body } = res;
      if (code >= 200 && code < 300) {
        ackSuccess(op, body);
        dropHead(op);
        // The new occurrence (a whole subtree with server ids) exists only on
        // the server, so reload to bring it in.
        if (OPS[op.kind]?.reloadAfterAck) await refetchAndRebuild();
        return true;
      }
      const spec = OPS[op.kind] || {};
      if (code === 400 && spec.on400) {
        dropHead(op);
        log("drop", spec.on400.log);
        await refetchAndRebuild();
        return true;
      }
      if (code === 409) {
        if (spec.retryOn409) {
          op.conflicts += 1;
          log("conflict", `${op.kind} #${op.conflicts}, server v${body && body.version}`);
          const node = model.todosById.get(op.target_id);
          if (op.conflicts > MAX_CONFLICTS || !node || !body) {
            return failPermanently(op, "kept conflicting with changes from another device");
          }
          // Local wins: adopt the server's version and any fields we did not edit.
          if (spec.onConflict) spec.onConflict(node, op, body);
          node.version = body.version;
          op.txn_id = uuid();
          op.state = "pending";
          persist();
          onChange();
          return true;
        }
        dropHead(op);
        log("conflict", `${op.kind}: reloading from the server`);
        notice("info", "Changed on another device; reloaded.");
        await refetchAndRebuild();
        return true;
      }
      if (code === 404 && spec.on404) {
        dropHead(op);
        log("drop", spec.on404.log);
        if (spec.on404.notice) notice("info", spec.on404.notice);
        await refetchAndRebuild();
        return true;
      }
      if (code === 404 && !(body && typeof body.detail === "string" && /todo not found/i.test(body.detail))) {
        // A route 404 (older/newer server instance) says nothing about the
        // item: retry, and after a few tries reconcile with the server rather
        // than delete anything locally.
        if (op.attempts < 3) {
          log("retry", `${op.kind}: 404 without a todo-not-found body`);
          scheduleRetry(op);
          return false;
        }
        dropHead(op);
        log("drop", `${op.kind}: repeated 404, reloading from the server`);
        await refetchAndRebuild();
        return true;
      }
      if (code === 404) {
        log("drop", `${op.kind}: 404, item is gone`);
        const target = op.target_id;
        removeOps((o) => o.target_id === target);
        for (const n of subtreeNodes(model, target)) model.todosById.delete(n.todo_id);
        const gone = model.todosById.get(target);
        if (!gone) model.roots = model.roots.filter((r) => r.todo_id !== target);
        for (const n of model.todosById.values()) {
          n.child_ids = n.child_ids.filter((c) => model.todosById.has(c));
        }
        persist();
        onChange();
        notice("info", "That item no longer exists on the server.");
        return true;
      }
      if (code === 401 || code === 403 || code === 408) {
        // Expired session / signed out / timeout: the edit is still wanted, so
        // hold it and retry (the fetch wrapper refreshes the token each time).
        authBlocked = code !== 408;
        log("retry", `${op.kind}: ${code}, keeping the edit`);
        scheduleRetry(op);
        return false;
      }
      if (code >= 500 || code === 429) {
        scheduleRetry(op);
        return false;
      }
      const detail = body && typeof body.detail === "string" ? `: ${body.detail}` : "";
      return failPermanently(op, `the server rejected it (${code})${detail}`);
    }

    async function failPermanently(op, why) {
      log("drop", `${op.kind}: ${why}`);
      dropHead(op);
      lastError = true;
      notice("error", `Couldn't save your ${op.kind}: ${why}.`);
      await refetchAndRebuild();
      return true;
    }

    async function run() {
      if (running || backoffTimer !== null) return;
      running = true;
      if (!ops.length) parked = false;
      try {
        while (ops.length) {
          if (!forceOnline && !isOnline()) {
            if (!parked) {
              parked = true;
              log("offline", `holding ${ops.length} edit(s) until the device is online`);
              emitStatus();
            }
            break;
          }
          if (needTree) {
            if (!parked) {
              parked = true;
              log("hold", `${ops.length} restored edit(s) wait for the first tree load`);
              emitStatus();
            }
            break;
          }
          parked = false;
          const op = ops[0];
          if (!OPS[op.kind]?.mintsTarget && isTmp(op.target_id)) {
            // Its parent create/split never landed, so there is nothing to target.
            dropHead(op);
            continue;
          }
          op.state = "sending";
          op.sent = true;
          emitStatus();
          const version = nodeOf(op.target_id)?.version;
          let res;
          const startedAt = Date.now();
          try {
            res = await send(buildRequest(op, version));
          } catch (e) {
            log("send-fail", `${op.kind} ${e && e.message ? e.message : e} (${Date.now() - startedAt}ms)`);
            authBlocked = !!(e && e.message === "Sign in required");
            scheduleRetry(op);
            break;
          }
          log("send", `${op.kind} ${res.status} (${Date.now() - startedAt}ms) rev ${res.prev ?? "?"}->${res.rev ?? "?"}`);
          observeRev(res.prev, res.rev);
          let proceed;
          try {
            proceed = await handle(op, res);
          } catch (e) {
            // A malformed reply must not strand the op in "sending" with no timer.
            log("handle-fail", `${op.kind} ${e && e.message ? e.message : e}`);
            scheduleRetry(op);
            break;
          }
          emitStatus();
          if (!proceed) break;
        }
      } finally {
        running = false;
        forceOnline = false;
        emitStatus();
        settleIfIdle();
      }
    }

    // -- public
    function kick(force = false) {
      if (force) forceOnline = true;
      if (backoffTimer !== null) {
        timers.clearTimeout(backoffTimer);
        backoffTimer = null;
      }
      run();
    }

    function flush() {
      return new Promise((resolvePromise) => {
        waiters.push(resolvePromise);
        run();
        settleIfIdle();
      });
    }

    async function load() {
      const saved = await store.load();
      ops = (saved || []).map((o) => ({ ...o, state: "pending" }));
      needTree = ops.length > 0;
      log("outbox", `${ops.length} unsent edit(s) restored`);
      emitStatus();
    }

    // The server keeps its replay log (txn_log) for 30 days. A create/split that
    // was sent and then sat in the outbox nearly that long may already be
    // committed but unacked; replaying it would duplicate it, so rebuild()
    // checks it against the server tree first.
    const isSuspect = (op) =>
      op.sent && OPS[op.kind]?.mayCommitUnacked &&
      typeof op.queued_at === "number" && now() - op.queued_at > SUSPECT_AGE_MS;

    // The server sends instants with a "Z"; trees cached before that have bare
    // UTC strings, which Date.parse would read as local time.
    const parseServerInstant = (s) => Date.parse(/(Z|[+-]\d\d:?\d\d)$/i.test(s) ? s : `${s}Z`);

    // True when the server tree already holds what a suspect (old, sent) op
    // would create, made after the op was queued.
    function alreadyCommitted(op, todosById) {
      const since = op.queued_at - 60000;
      const fresh = (t) => !t.deleted && parseServerInstant(t.create_date) >= since;
      return OPS[op.kind].alreadyCommitted(op, todosById, fresh);
    }

    // Replace the model with a fresh server tree and re-apply everything still
    // in the outbox on top of it, so unsent edits stay visible.
    function rebuild(tree) {
      const todosById = tree.todosById;
      needTree = false;
      const before = ops.length;
      ops = ops.filter((op) => {
        if (!isSuspect(op) || !alreadyCommitted(op, todosById)) return true;
        log("drop", `${op.kind}: already on the server (old outbox), not replaying`);
        return false;
      });
      if (ops.length !== before) { epoch += 1; persist(); }
      model.todosById = todosById;
      model.roots = tree.roots.map((r) => todosById.get(r.todo_id) || r);
      model.trash = new Map();
      if (tree.rev != null) {
        knownRev = tree.rev;
        stale = false;
      }
      for (const op of ops) {
        // Every op still queued is unacknowledged (acked ops leave the
        // outbox), so a move is re-applied even if `sent`: it may have failed
        // or been restored from storage, and a replay is idempotent by txn_id.
        applyOp(model, op);
      }
      log("rebuild", `rev ${tree.rev ?? "?"}, ${todosById.size} todos, ${ops.length} pending`);
      onChange();
      if (parked && ops.length) run(); // held for the first tree: go now
    }

    return {
      enqueue, load, rebuild, flush, kick, resolve,
      pending: () => ops.length,
      needsTree: () => needTree,
      epoch: () => epoch,
      knownRev: () => knownRev,
      isStale: () => stale,
      noteRemoteRev,
      observeRev,
      status,
      saved: () => saveChain,
    };
  }

  return { createModel, applyOp, clearableIds, buildRequest, createEngine, normalizeDue, isTmp, OPS };
});
