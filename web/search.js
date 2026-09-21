// Client-side search over the todo tree already in memory. Case-insensitive,
// diacritic-insensitive, every word must match (AND) somewhere in the title,
// link urls/labels or color name. No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Search = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function normalize(s) {
    return String(s == null ? "" : s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function words(query) {
    return normalize(query).split(/\s+/).filter(Boolean);
  }

  function extraText(todo) {
    const parts = [todo.color];
    for (const l of Array.isArray(todo.links) ? todo.links : []) {
      if (l) parts.push(l.url, l.label);
    }
    return normalize(parts.filter(Boolean).join(" "));
  }

  function ancestorsOf(todo, todosById) {
    const ids = [];
    const seen = new Set([todo.todo_id]);
    let p = todo.parent_id != null ? todosById.get(String(todo.parent_id)) : null;
    while (p && !seen.has(p.todo_id)) {
      seen.add(p.todo_id);
      ids.unshift(p.todo_id);
      p = p.parent_id != null ? todosById.get(String(p.parent_id)) : null;
    }
    return ids;
  }

  // -> [{ todo, path: [titles], ancestorIds, titleHit }], best first.
  function search(todosById, query) {
    const ws = words(query);
    if (!ws.length) return [];
    const hits = [];
    for (const todo of todosById.values()) {
      const title = normalize(todo.title);
      const all = title + " " + extraText(todo);
      if (!ws.every((w) => all.includes(w))) continue;
      const ancestorIds = ancestorsOf(todo, todosById);
      hits.push({
        todo,
        ancestorIds,
        path: ancestorIds.map((id) => todosById.get(id).title),
        titleHit: ws.every((w) => title.includes(w)),
      });
    }
    // Open before done, then title hits before link/color hits. Sort is stable.
    return hits.sort(
      (a, b) => (a.todo.done ? 1 : 0) - (b.todo.done ? 1 : 0) || (b.titleHit ? 1 : 0) - (a.titleHit ? 1 : 0),
    );
  }

  return { normalize, search };
});
