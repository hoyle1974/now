// "Finish the last subtask, finish the parent": which ancestors become done
// once `id` is done. One-way by design: nothing here ever reopens a parent.
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Autodone = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Ancestor ids to mark done, nearest first. `id` itself counts as done even if
  // the model has not caught up yet.
  function ancestorsToComplete(model, id) {
    const out = [];
    const willBeDone = new Set([id]);
    let node = model.todosById.get(id);
    while (node && node.parent_id) {
      const parent = model.todosById.get(node.parent_id);
      if (!parent || parent.done) break;
      const allDone = parent.child_ids.every((cid) => {
        const c = model.todosById.get(cid);
        return !c || c.done || willBeDone.has(cid);
      });
      if (!allDone) break;
      out.push(parent.todo_id);
      willBeDone.add(parent.todo_id);
      node = parent;
    }
    return out;
  }

  return { ancestorsToComplete };
});
