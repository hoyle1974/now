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
- **Archive:** todos deleted 30+ days ago, with everything beneath, move `todos` → `todos_archive` (`archive_expired`); deleting stamps `deleted_at`; sweep runs at most daily, triggered by `/todos/tree` and `/todos/next`. Each chunk (200 docs) moves in a transaction that re-reads its documents: one that changed since the candidate scan (undeleted, edited, reparented) stays, with everything beneath it, until the next run; the move bumps rev. The daily `last_run` is claimed in a transaction, so one instance runs it. A naive stored timestamp is read as UTC. Archiving also deletes the todos' images from the bucket, and the run ends with `sweep_orphan_blobs` (deletes blobs over an hour old that no todo lists) ([attachments](attachments.md)). Archived todos leave Trash and can't be restored from the UI. See [Firestore](../data/firestore.md).
- **Tree cache:** `get_tree` reuses its result while rev is unchanged.
