// What changed between two copies of the tree, for the mascot to announce after
// another window or device wrote. No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.RemoteDiff = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // id -> what matters for a diff. View-only state (collapsed) is left out: it
  // doesn't bump the version and isn't worth announcing.
  function snapshot(todosById) {
    const out = new Map();
    for (const [id, n] of todosById) {
      out.set(id, { version: n.version, done: !!n.done, title: n.title, by: n.last_edited_by || null,
        shareRoot: !!n.share_root, owner: n.share ? n.share.owner : null });
    }
    return out;
  }

  // Ids that came, went or changed between two snapshots.
  function diff(before, after) {
    const added = [], removed = [], changed = [];
    for (const [id, now] of after) {
      const was = before.get(id);
      if (!was) added.push({ id, ...now });
      else if (was.version !== now.version || was.done !== now.done || was.title !== now.title) {
        changed.push({ id, ...now, wasDone: was.done, wasTitle: was.title });
      }
    }
    for (const [id, was] of before) if (!after.has(id)) removed.push({ id, ...was });
    return { added, removed, changed };
  }

  function short(title, max = 28) {
    const t = String(title || "").trim().replace(/\s+/g, " ");
    return t.length > max ? t.slice(0, max - 1) + "…" : t;
  }

  const nameOf = (email) => String(email).split("@")[0];

  // The line the mascot says, or "" when nothing changed. `me` (the signed-in email)
  // lets a change in a shared item name the person who made it.
  function describe({ added, removed, changed }, me = null) {
    const total = added.length + removed.length + changed.length;
    if (total === 0) return "";
    const other = (email) => email && me && email !== me;
    // A share coming or going brings its whole subtree: one line about the share.
    const arrived = added.find((a) => a.shareRoot && other(a.owner));
    if (arrived) return `${nameOf(arrived.owner)} shared “${short(arrived.title)}” with everyone`;
    const left = removed.find((r) => r.shareRoot && other(r.owner));
    if (left) return `${nameOf(left.owner)} stopped sharing “${short(left.title)}”`;
    if (total > 1) return `${total} changes from another device`;
    if (added.length) {
      const a = added[0];
      if (other(a.by)) return `${nameOf(a.by)} added “${short(a.title)}”`;
      return `New from another device: “${short(a.title)}”`;
    }
    if (removed.length) return `“${short(removed[0].title)}” was removed on another device`;
    const c = changed[0];
    if (other(c.by)) {
      if (c.done && !c.wasDone) return `${nameOf(c.by)} checked off “${short(c.title)}”`;
      if (!c.done && c.wasDone) return `${nameOf(c.by)} reopened “${short(c.title)}”`;
      return `${nameOf(c.by)} updated “${short(c.title)}”`;
    }
    if (c.done && !c.wasDone) return `“${short(c.title)}” was checked off on another device`;
    if (!c.done && c.wasDone) return `“${short(c.title)}” was reopened on another device`;
    return `“${short(c.title)}” was updated on another device`;
  }

  return { snapshot, diff, describe };
});
