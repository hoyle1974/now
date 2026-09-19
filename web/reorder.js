// Turns "dragged row X was dropped on row Y here" into a reparent instruction.
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Reorder = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const byOrder = (a, b) => (a.order_idx ?? 999999) - (b.order_idx ?? 999999);

  // Siblings in display order (the same order the sync engine's ops use).
  function siblingsOf(model, parentId) {
    const list = parentId
      ? (model.todosById.get(parentId)?.child_ids || []).map((id) => model.todosById.get(id)).filter(Boolean)
      : model.roots.slice();
    return list.sort(byOrder);
  }

  function inSubtree(model, rootId, id) {
    if (rootId === id) return true;
    const node = model.todosById.get(rootId);
    return node ? node.child_ids.some((c) => inSubtree(model, c, id)) : false;
  }

  // The top ~30% of a row means "just above it", the bottom ~30% "just below
  // it", and the middle means "make it a child of this row".
  function zoneFor(rect, y) {
    const t = (y - rect.top) / rect.height;
    if (t < 0.3) return "before";
    if (t > 0.7) return "after";
    return "inside";
  }

  // zone: "before" | "after" | "inside" relative to the target row.
  // Returns {parent_id, index} for a reparent op (index null = last child), or
  // null when the drop is invalid or would change nothing.
  function planDrop(model, draggedId, targetId, zone) {
    const node = model.todosById.get(draggedId);
    const target = model.todosById.get(targetId);
    if (!node || !target || draggedId === targetId) return null;
    if (inSubtree(model, draggedId, targetId)) return null;

    if (zone === "inside") {
      const kids = siblingsOf(model, targetId);
      if (kids.length && kids[kids.length - 1] === node) return null;
      return { parent_id: targetId, index: null };
    }

    const parentId = target.parent_id ?? null;
    const others = siblingsOf(model, parentId).filter((s) => s !== node);
    const at = others.indexOf(target);
    const index = zone === "before" ? at : at + 1;

    if ((node.parent_id ?? null) === parentId) {
      const current = siblingsOf(model, parentId).indexOf(node);
      if (current === index) return null;
    }
    return { parent_id: parentId, index };
  }

  // Long-press arming: onArm fires once the pointer has stayed within `slop`
  // px of where it went down for `delay` ms. Moving further (a scroll) or
  // releasing first cancels. Timer functions are injectable for tests.
  function longPress(onArm, opts = {}) {
    const delay = opts.delay ?? 350;
    const slop = opts.slop ?? 8;
    const set = opts.setTimeout || ((f, ms) => setTimeout(f, ms));
    const clear = opts.clearTimeout || ((id) => clearTimeout(id));
    let timer = null, x0 = 0, y0 = 0;
    const press = {
      armed: false,
      start(x, y) {
        press.end();
        x0 = x; y0 = y;
        timer = set(() => { timer = null; press.armed = true; onArm(); }, delay);
      },
      move(x, y) {
        if (timer !== null && Math.hypot(x - x0, y - y0) > slop) press.cancel();
      },
      cancel() { if (timer !== null) { clear(timer); timer = null; } },
      end() { press.cancel(); press.armed = false; },
    };
    return press;
  }

  return { planDrop, zoneFor, longPress };
});
