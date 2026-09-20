---
type: Feature
title: Trash, clear completed and archive
description: Soft delete, undo, and 30-day archive to todos_archive.
resource: app/db_firestore.py
tags: [delete, archive]
timestamp: 2026-09-19T00:00:00Z
---
- **Clear completed:** `POST /todos/clear-completed`, one transaction soft-deletes every done todo whose whole subtree is done (only the topmost of each subtree is flagged, so undo restores the subtree). Toast Undo queues an `undelete` per item.
- **Trash** (`web/trash.js`): `GET /todos/trash`; restore with `undelete`. If an ancestor is also deleted the todo restores at top level.
- **Archive:** todos deleted 30+ days ago, with everything beneath, move `todos` → `todos_archive` (`archive_expired`); deleting stamps `deleted_at`; sweep runs at most daily, triggered by `/todos/tree` and `/todos/next`. Archived todos leave Trash and can't be restored from the UI. See [Firestore](../data/firestore.md).
- **Tree cache:** `get_tree` reuses its result while rev is unchanged.
