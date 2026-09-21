// "Finish the last subtask, finish the parent": which ancestors become done
// once `id` is done. One-way by design: nothing here ever reopens a parent.
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./types.js"));
  } else {
    root.Autodone = factory(root.Types);
  }
})(typeof self !== "undefined" ? self : this, function (Types) {
  "use strict";

  // Every todo beneath `parent` is done (or about to be). Containers have no done state,
  // so they are looked through to the todos inside them.
  function allDone(model, parent, willBeDone) {
    return parent.child_ids.every((cid) => {
      const c = model.todosById.get(cid);
      if (!c) return true;
      if (!Types.can(c, "hasCheckbox")) return allDone(model, c, willBeDone);
      return c.done || willBeDone.has(cid);
    });
  }

  // Ancestor ids to mark done, nearest first. `id` itself counts as done even if
  // the model has not caught up yet. A container is passed through, never completed.
  function ancestorsToComplete(model, id) {
    const out = [];
    const willBeDone = new Set([id]);
    let node = model.todosById.get(id);
    while (node && node.parent_id) {
      const parent = model.todosById.get(node.parent_id);
      if (!parent) break;
      if (Types.can(parent, "triggersAutodone")) {
        if (parent.done || !allDone(model, parent, willBeDone)) break;
        out.push(parent.todo_id);
        willBeDone.add(parent.todo_id);
      }
      node = parent;
    }
    return out;
  }

  return { ancestorsToComplete };
});
