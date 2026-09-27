// Shared items on the client: what the signed-in person may do with a node from a
// share, its badge, and whether a drag crosses a share's edge. Pure logic, no DOM, so it
// runs under `node --test`; the permission table mirrors tests/fixtures/share_rules.json
// (tests_js/share-rules.test.js checks they agree). The server enforces all of this; the
// client only avoids offering what would be refused (docs/okf/features/sharing.md).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.ShareUI = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // role -> actions allowed. A node that isn't shared allows everything.
  const OWNER_ONLY = new Set(["delete_root", "change_mode", "unshare"]);
  const READ_ONLY_OK = new Set(["read", "collapse", "move_mount"]);

  function role(node, me) {
    const share = node && node.share;
    if (!share) return null;
    if (me && share.owner === me) return "owner";
    return share.mode === "ro" ? "ro" : "rw";
  }

  function can(node, action, me) {
    const r = role(node, me);
    if (r === null || r === "owner") return true;
    if (r === "ro") return READ_ONLY_OK.has(action);
    return !OWNER_ONLY.has(action);
  }

  // May the row be edited at all (checkbox, title, fields, add, delete a child)?
  const editable = (node, me) => can(node, "edit_child", me);

  const localPart = (email) => String(email || "").split("@")[0] || null;

  // null for an item of your own; the label only on the share's root.
  function badge(node, me) {
    const share = node && node.share;
    if (!share) return null;
    if (!node.share_root) return { icon: true, label: null, by: null };
    return {
      icon: true,
      label: share.mode === "ro" ? "Shared · read-only" : "Shared · can edit",
      by: share.owner === me ? null : localPart(share.owner),
    };
  }

  // Which share a node's data lives in: a share root lives in your list (as your mount).
  function homeOf(node) {
    return node && node.share && !node.share_root ? node.share.id : null;
  }

  // Which share a new child of this parent would live in (null: your own list).
  function shareUnder(model, parentId) {
    const parent = parentId ? model.todosById.get(parentId) : null;
    return parent && parent.share ? parent.share.id : null;
  }

  // Would dropping nodeId under targetParentId move data between partitions?
  function crossesEdge(model, nodeId, targetParentId) {
    const node = model.todosById.get(nodeId);
    const from = homeOf(node);
    const to = shareUnder(model, targetParentId);
    if (node && node.share_root) {
      // Your mount: it moves within your own list, never into a share.
      return { crosses: false, into: null, outOf: null, allowed: to === null };
    }
    if (from === to) return { crosses: false, into: null, outOf: null, allowed: true };
    return { crosses: true, into: to, outOf: from, allowed: true };
  }

  // Drag targeting: may this node go under that parent at all?
  function dropAllowed(model, nodeId, targetParentId, me) {
    const node = model.todosById.get(nodeId);
    const edge = crossesEdge(model, nodeId, targetParentId);
    if (!edge.allowed) return false;
    if (node && node.share_root) return true;
    const parent = targetParentId ? model.todosById.get(targetParentId) : null;
    if (node && node.share && !can(node, "drag_across", me)) return false;
    if (parent && parent.share && !can(parent, "add_child", me)) return false;
    return true;
  }

  // The confirm shown before a drag that crosses an edge, or null when none is needed.
  function crossingMessage(model, nodeId, targetParentId) {
    const edge = crossesEdge(model, nodeId, targetParentId);
    if (!edge.crosses) return null;
    const title = `“${(model.todosById.get(nodeId) || {}).title || "this item"}”`;
    return edge.into ? `Everyone will see ${title}.` : `This removes ${title} for everyone else.`;
  }

  return { can, editable, badge, crossesEdge, dropAllowed, crossingMessage, localPart };
});
