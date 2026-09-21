// Pure helpers for the per-todo color, links, blocked_by and references
// fields. No DOM access, so it runs unchanged under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./types.js"));
  } else {
    root.Fields = factory(root.Types);
  }
})(typeof self !== "undefined" ? self : this, function (Types) {
  "use strict";

  const COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"];
  const MAX_LINKS = 20;

  const isTmp = (id) => typeof id === "string" && id.startsWith("tmp:");

  // The server's `blocked` flag is only right in the full tree, so recompute it
  // from the local model: blocked while any blocker still exists and is open.
  function isBlocked(todo, todosById) {
    return (todo.blocked_by || []).some((id) => {
      const b = todosById.get(id);
      return !!b && !b.deleted && !b.done && Types.can(b, "hasCheckbox");
    });
  }

  // Todos for a list of ids, skipping ids that are no longer in the model.
  function resolveRefs(ids, todosById) {
    return (ids || []).map((id) => todosById.get(id)).filter(Boolean);
  }

  function isSafeUrl(url) {
    try {
      const p = new URL(url).protocol;
      return p === "http:" || p === "https:";
    } catch (e) {
      return false;
    }
  }

  // Trim and validate the editor's link rows. Rows with no url are dropped.
  function cleanLinks(rows) {
    const links = [];
    for (const row of rows || []) {
      const url = (row.url || "").trim();
      if (!url) continue;
      if (!isSafeUrl(url)) return { links: null, error: `"${url}" is not an http or https link.` };
      const label = (row.label || "").trim();
      links.push({ url, label: label || null });
    }
    if (links.length > MAX_LINKS) return { links: null, error: `At most ${MAX_LINKS} links.` };
    return { links, error: null };
  }

  // A todo's own color, else the nearest colored ancestor's, else null.
  function effectiveColor(todo, todosById) {
    const seen = new Set();
    for (let node = todo; node && !seen.has(node.todo_id); node = node.parent_id ? todosById.get(node.parent_id) : null) {
      if (COLORS.includes(node.color)) return node.color;
      seen.add(node.todo_id);
    }
    return null;
  }

  // Other todos to choose from, filtered by a title search. Temp ids are left
  // out (the server doesn't know them yet), as are deleted todos and self.
  // Ids of a todo's ancestors and descendants: a todo already waits on its own
  // subtasks, so these make no sense as blockers.
  function relativeIds(todosById, id) {
    const out = new Set();
    let node = todosById.get(id);
    while (node && node.parent_id && !out.has(node.parent_id)) {
      out.add(node.parent_id);
      node = todosById.get(node.parent_id);
    }
    const stack = [...((todosById.get(id) || {}).child_ids || [])];
    while (stack.length) {
      const cid = stack.pop();
      if (out.has(cid)) continue;
      out.add(cid);
      stack.push(...((todosById.get(cid) || {}).child_ids || []));
    }
    return out;
  }

  function pickerCandidates(todosById, selfId, query, selectedIds, exclude = new Set()) {
    const q = (query || "").trim().toLowerCase();
    const out = [];
    for (const todo of todosById.values()) {
      if (todo.todo_id === selfId || todo.deleted || isTmp(todo.todo_id) || exclude.has(todo.todo_id)) continue;
      if (q && !(todo.title || "").toLowerCase().includes(q)) continue;
      out.push({ todo, selected: selectedIds.has(todo.todo_id) });
    }
    // Selected first so they can be un-picked, then by title.
    out.sort((a, b) => (b.selected - a.selected) || (a.todo.title || "").localeCompare(b.todo.title || ""));
    return out;
  }

  function sameIds(a, b) {
    const x = a || [];
    const y = b || [];
    return x.length === y.length && x.every((id) => y.includes(id));
  }

  const sameLinks = (a, b) => JSON.stringify(a || []) === JSON.stringify(b || []);

  // Only the fields that differ from the todo, so saving never overwrites a
  // field the user didn't touch (which another device may have changed).
  function changedFields(todo, next) {
    const out = {};
    if ((todo.color ?? null) !== (next.color ?? null)) out.color = next.color ?? null;
    if (!sameLinks(todo.links, next.links)) out.links = next.links;
    if (!sameIds(todo.blocked_by, next.blocked_by)) out.blocked_by = next.blocked_by;
    if (!sameIds(todo.references, next.references)) out.references = next.references;
    return out;
  }

  // PATCH body for an edit. `dueDate` undefined = a rename: send only the title
  // so the due time and repeat rule stay untouched. Otherwise null/"" clears the
  // due date, and a repeat rule needs a date.
  function patchPayload({ title, dueDate, repeat = null, fields = {} }) {
    if (dueDate === undefined) return { title, ...fields };
    return { title, due_date: dueDate || null, repeat: dueDate ? repeat : null, ...fields };
  }

  return { patchPayload, COLORS, effectiveColor, MAX_LINKS, isBlocked, resolveRefs, isSafeUrl, cleanLinks, relativeIds, pickerCandidates, sameIds, changedFields };
});
