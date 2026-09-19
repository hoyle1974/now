// Optimistic-edit sync engine: a local model, an ordered outbox of ops, and a
// single-flight loop that sends them with retry, idempotency and version
// checks. No DOM access, so it runs unchanged under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Sync = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const MAX_CONFLICTS = 3;
  const BACKOFF_BASE_MS = 1000;
  const BACKOFF_CAP_MS = 30000;
  const PATCH_FIELDS = ["title", "done", "due_date"];

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

  function newNode(id, title, dueDate, parentId, orderIdx) {
    return {
      todo_id: id, title, done: false, create_date: new Date().toISOString(),
      due_date: normalizeDue(dueDate), order_idx: orderIdx, parent_id: parentId,
      child_ids: [], deleted: false, version: 0,
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

  // Apply an op to the local model. Returns false when it can't apply
  // (unknown target, move off the end of the list, ...).
  function applyOp(model, op) {
    const { kind, target_id: id, payload = {} } = op;
    switch (kind) {
      case "create": {
        if (model.todosById.has(id)) return false;
        const node = newNode(id, payload.title, payload.due_date, null, null);
        model.todosById.set(id, node);
        model.roots.push(node);
        return true;
      }
      case "patch": {
        const node = model.todosById.get(id);
        if (!node) return false;
        for (const f of PATCH_FIELDS) {
          if (f in payload) node[f] = f === "due_date" ? normalizeDue(payload[f]) : payload[f];
        }
        return true;
      }
      case "delete": {
        const node = model.todosById.get(id);
        if (!node) return false;
        const nodes = subtreeNodes(model, id);
        const index = detach(model, node);
        model.trash.set(id, { nodes, parent_id: node.parent_id, index });
        nodes.forEach((n) => model.todosById.delete(n.todo_id));
        return true;
      }
      case "undelete": {
        const snap = model.trash.get(id);
        if (!snap) return false;
        model.trash.delete(id);
        snap.nodes.forEach((n) => model.todosById.set(n.todo_id, n));
        const node = snap.nodes[0];
        const parent = snap.parent_id ? model.todosById.get(snap.parent_id) : null;
        const list = parent ? parent.child_ids : model.roots;
        const item = parent ? id : node;
        list.splice(Math.min(Math.max(snap.index, 0), list.length), 0, item);
        return true;
      }
      case "split": {
        const parent = model.todosById.get(id);
        if (!parent) return false;
        const tmpIds = payload.child_tmp_ids || [];
        let next = Math.max(-1, ...parent.child_ids.map((c) => model.todosById.get(c)?.order_idx ?? -1)) + 1;
        payload.descriptions.forEach((title, i) => {
          if (model.todosById.has(tmpIds[i])) return;
          const child = newNode(tmpIds[i], title, payload.due_date, id, next++);
          model.todosById.set(child.todo_id, child);
          parent.child_ids.push(child.todo_id);
        });
        return true;
      }
      case "move": {
        const node = model.todosById.get(id);
        const parent = node && node.parent_id ? model.todosById.get(node.parent_id) : null;
        if (!parent) return false;
        const sibs = sortedSiblings(model, parent);
        if (sibs.length < 2) return false;
        const pos = sibs.indexOf(node);
        const to = payload.direction === "up" ? pos - 1 : pos + 1;
        if (to < 0 || to >= sibs.length) return false;
        sibs.splice(pos, 1);
        sibs.splice(to, 0, node);
        sibs.forEach((s, i) => { s.order_idx = i; });
        parent.child_ids = sibs.map((s) => s.todo_id);
        return true;
      }
      default:
        return false;
    }
  }

  // ---- requests ---------------------------------------------------------

  function buildRequest(op, version) {
    const headers = { "Content-Type": "application/json", "X-Txn-Id": op.txn_id };
    const id = op.target_id;
    const p = op.payload || {};
    const conditional = () => {
      if (version != null && version > 0) headers["If-Match"] = String(version);
    };
    switch (op.kind) {
      case "create": {
        const body = { title: p.title };
        if (p.due_date) body.due_date = p.due_date;
        return { method: "POST", path: "/todos", headers, body };
      }
      case "patch": {
        conditional();
        const body = {};
        for (const f of PATCH_FIELDS) if (f in p) body[f] = p[f];
        return { method: "PATCH", path: `/todos/${id}`, headers, body };
      }
      case "delete":
        conditional();
        return { method: "DELETE", path: `/todos/${id}`, headers };
      case "undelete":
        // Undo of a delete we just made: nothing to be stale against.
        return { method: "PATCH", path: `/todos/${id}/undelete`, headers };
      case "split": {
        conditional();
        const body = { descriptions: p.descriptions };
        if (p.due_date) body.due_date = p.due_date;
        return { method: "POST", path: `/todos/${id}/split`, headers, body };
      }
      case "move":
        conditional();
        return { method: "PATCH", path: `/todos/${id}/move/${p.direction}`, headers };
      default:
        throw new Error("unknown op kind " + op.kind);
    }
  }

  // ---- engine -----------------------------------------------------------

  function createEngine(opts) {
    const { model, store, send, refetch } = opts;
    const onChange = opts.onChange || (() => {});
    const onStatus = opts.onStatus || (() => {});
    const onNotice = opts.onNotice || (() => {});
    const onRemap = opts.onRemap || (() => {});
    const timers = opts.timers || { setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (t) => clearTimeout(t) };
    const random = opts.random || Math.random;
    const uuid = opts.uuid || defaultUuid;

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
    let saveChain = Promise.resolve();
    const waiters = [];

    // -- persistence / status
    function persist() {
      const snapshot = JSON.parse(JSON.stringify(ops));
      saveChain = saveChain.then(() => store.save(snapshot)).catch(() => {});
      return saveChain;
    }

    function status() {
      let state = "synced";
      if (backoffTimer !== null) state = "offline";
      else if (ops.length) state = "syncing";
      else if (lastError) state = "error";
      return { state, pending: ops.length };
    }

    function emitStatus() { onStatus(status()); }

    function settleIfIdle() {
      if (!running && (ops.length === 0 || backoffTimer !== null)) {
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
      if (knownRev !== null && prev > knownRev) stale = true;
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
      for (const op of ops) if (op.target_id === tmp) op.target_id = real;

      const trashed = model.trash.get(tmp);
      if (trashed) {
        // Deleted before its create landed: keep the undo snapshot under the real id.
        model.trash.delete(tmp);
        model.trash.set(real, trashed);
        trashed.nodes[0].todo_id = real;
        for (const n of trashed.nodes.slice(1)) if (n.parent_id === tmp) n.parent_id = real;
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
          if (list) list[list.indexOf(tmp)] = real;
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
      for (let i = ops.length - 1; i >= 0; i--) {
        const prev = ops[i];
        if (prev.target_id !== op.target_id) continue;
        if (prev.state !== "pending") return false;
        if (op.kind === "patch" && prev.kind === "patch") {
          Object.assign(prev.payload, op.payload);
          return true;
        }
        if (op.kind === "undelete" && prev.kind === "delete") {
          ops.splice(i, 1);
          return true;
        }
        return false;
      }
      return false;
    }

    // Returns the target id (the new temp id for a create), or false if the
    // op can't apply locally.
    function enqueue({ kind, target_id, payload = {} }) {
      const op = {
        txn_id: uuid(), kind,
        target_id: kind === "create" ? "tmp:" + uuid() : resolve(target_id),
        payload: { ...payload }, state: "pending", attempts: 0, conflicts: 0, sent: false,
      };
      if (kind === "split" && !op.payload.child_tmp_ids) {
        op.payload.child_tmp_ids = op.payload.descriptions.map(() => "tmp:" + uuid());
      }
      const applied = applyOp(model, op);
      if (!applied && kind !== "undelete") return false;
      if (!tryCoalesce(op)) ops.push(op);
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
      backoffTimer = timers.setTimeout(() => {
        backoffTimer = null;
        run();
      }, backoffDelay(op.attempts));
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

    function ackSuccess(op, body) {
      lastError = false;
      switch (op.kind) {
        case "create": {
          remapId(op.target_id, body.todo_id);
          const node = model.todosById.get(body.todo_id);
          if (node) Object.assign(node, { version: body.version, create_date: body.create_date, order_idx: body.order_idx });
          break;
        }
        case "patch":
        case "move": {
          const node = model.todosById.get(op.target_id);
          if (node && body) node.version = body.version;
          break;
        }
        case "split": {
          const aff = (body && body.affected) || [];
          const parent = model.todosById.get(op.target_id);
          if (parent && aff[0]) parent.version = aff[0].version;
          (op.payload.child_tmp_ids || []).forEach((tmp, i) => {
            if (!aff[i + 1]) return;
            remapId(tmp, aff[i + 1].todo_id);
            const child = model.todosById.get(aff[i + 1].todo_id);
            if (child) child.version = aff[i + 1].version;
          });
          break;
        }
        case "undelete":
          for (const a of (body && body.affected) || []) {
            const node = model.todosById.get(a.todo_id);
            if (node) node.version = a.version;
          }
          break;
        default:
          break;
      }
    }

    async function handle(op, res) {
      const { status: code, body } = res;
      if (code >= 200 && code < 300) {
        ackSuccess(op, body);
        dropHead(op);
        return true;
      }
      if (code === 409) {
        if (op.kind === "patch" || op.kind === "move") {
          op.conflicts += 1;
          const node = model.todosById.get(op.target_id);
          if (op.conflicts > MAX_CONFLICTS || !node || !body) {
            return failPermanently(op, "kept conflicting with changes from another device");
          }
          // Local wins: adopt the server's version and any fields we did not edit.
          if (op.kind === "patch") {
            for (const f of PATCH_FIELDS) {
              if (!(f in op.payload)) node[f] = f === "due_date" ? normalizeDue(body[f]) : body[f];
            }
          }
          node.version = body.version;
          op.txn_id = uuid();
          op.state = "pending";
          persist();
          onChange();
          return true;
        }
        dropHead(op);
        notice("info", "Changed on another device; reloaded.");
        await refetchAndRebuild();
        return true;
      }
      if (code === 404) {
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
      if (code >= 500 || code === 429) {
        scheduleRetry(op);
        return false;
      }
      return failPermanently(op, `the server rejected it (${code})`);
    }

    async function failPermanently(op, why) {
      dropHead(op);
      lastError = true;
      notice("error", `Couldn't save your ${op.kind}: ${why}.`);
      await refetchAndRebuild();
      return true;
    }

    async function run() {
      if (running || backoffTimer !== null) return;
      running = true;
      try {
        while (ops.length) {
          const op = ops[0];
          if (op.kind !== "create" && isTmp(op.target_id)) {
            // Its parent create/split never landed, so there is nothing to target.
            dropHead(op);
            continue;
          }
          op.state = "sending";
          op.sent = true;
          emitStatus();
          const version = model.todosById.get(op.target_id)?.version;
          let res;
          try {
            res = await send(buildRequest(op, version));
          } catch (e) {
            scheduleRetry(op);
            break;
          }
          observeRev(res.prev, res.rev);
          const proceed = await handle(op, res);
          emitStatus();
          if (!proceed) break;
        }
      } finally {
        running = false;
        emitStatus();
        settleIfIdle();
      }
    }

    // -- public
    function kick() {
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
      emitStatus();
    }

    // Replace the model with a fresh server tree and re-apply everything still
    // in the outbox on top of it, so unsent edits stay visible.
    function rebuild(tree) {
      const todosById = tree.todosById;
      model.todosById = todosById;
      model.roots = tree.roots.map((r) => todosById.get(r.todo_id) || r);
      model.trash = new Map();
      if (tree.rev != null) {
        knownRev = tree.rev;
        stale = false;
      }
      for (const op of ops) {
        // A move that may already have reached the server would apply twice.
        if (op.kind === "move" && op.sent) continue;
        applyOp(model, op);
      }
      onChange();
    }

    return {
      enqueue, load, rebuild, flush, kick, resolve,
      pending: () => ops.length,
      epoch: () => epoch,
      knownRev: () => knownRev,
      isStale: () => stale,
      noteRemoteRev,
      status,
      saved: () => saveChain,
    };
  }

  return { createModel, applyOp, buildRequest, createEngine, normalizeDue, isTmp };
});
