// Plain-text outline of a todo and its descendants, for pasting into other
// tools: "- " bullets, two spaces of indent per level, done items as "[x]".
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./types.js"));
  } else {
    root.Outline = factory(root.Types);
  }
})(typeof self !== "undefined" ? self : this, function (Types) {
  "use strict";

  function toOutline(todosById, rootId) {
    const lines = [];
    const seen = new Set();
    function walk(id, depth) {
      const todo = todosById.get(id);
      if (!todo || seen.has(id)) return;
      seen.add(id);
      lines.push(`${"  ".repeat(depth)}- ${todo.done && Types.can(todo, "hasCheckbox") ? "[x] " : ""}${todo.title}`);
      const children = todo.child_ids
        .map((childId) => todosById.get(childId))
        .filter(Boolean)
        .sort((a, b) => (a.order_idx ?? 999999) - (b.order_idx ?? 999999));
      for (const child of children) walk(child.todo_id, depth + 1);
    }
    walk(rootId, 0);
    return lines.join("\n");
  }

  return { toOutline };
});
