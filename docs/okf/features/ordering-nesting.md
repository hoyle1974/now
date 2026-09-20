---
type: Feature
title: Ordering and nesting
description: order_idx, drag handles, reparent op.
resource: web/reorder.js
tags: [ui, tree]
timestamp: 2026-09-19T00:00:00Z
---
Every todo, roots included, has an `order_idx`. Each row has a drag handle. Dropping above/below a row moves next to it; dropping on the middle makes it that row's last subtask. `web/reorder.js` turns the drop into `{parent_id, index}` and queues one `reparent` op (`PATCH /todos/{id}/reparent`), optimistic like any edit ([sync](sync-model.md)). Moving into the todo's own subtree is refused. See [routes](../api/routes.md).
