---
type: Feature
title: Ordering and nesting
description: order_idx, drag handles, reparent op.
resource: web/reorder.js
tags: [ui, tree]
timestamp: 2026-09-20T23:30:00Z
---
Every todo, roots included, has an `order_idx`. Each row has a drag handle. Dropping above/below a row moves next to it; dropping on the middle makes it that row's last subtask. `web/reorder.js` turns the drop into `{parent_id, index}` and queues one `reparent` op (`PATCH /todos/{id}/reparent`), optimistic like any edit ([sync](sync-model.md)). Moving into the todo's own subtree is refused. See [routes](../api/routes.md).

**Open sheets survive re-renders.** The New item / Add several / Edit sheets live inside the tree, and `renderTree()` rebuilds the whole tree on every change (a sync ack, folding a subtask, a refresh). `web/tree-view.js` snapshots the open sheet's field values, focus and caret before the rebuild and restores them after (`snapshotSheet` / `restoreSheet`), only if the same panel (mode + todo id) is still open. Color and link edits are JS state, not fields, and are not carried over.
