---
type: Feature
title: Trash, clear completed and archive
description: Soft delete, undo, and 30-day archive to todos_archive.
resource: app/db_firestore.py
tags: [delete, archive]
timestamp: 2026-09-21T18:00:00Z
---
- **Clear completed:** `POST /todos/clear-completed`, one transaction soft-deletes every done todo whose whole subtree is done (only the topmost of each subtree is flagged, so undo restores the subtree). Toast Undo queues an `undelete` per item.
- **Trash** (`web/trash.js`): its own screen (the List / Next up control is hidden, accent-colored Back button); `GET /todos/trash` (most recently deleted first, by `deleted_at`); restore with `undelete`. If an ancestor is also deleted the todo restores at top level.
- **Archive:** todos deleted 30+ days ago, with everything beneath, move `todos` → `todos_archive` (`archive_expired`); deleting stamps `deleted_at`; sweep runs at most daily, as a FastAPI background task after `/todos/tree` and `/todos/next` respond (one at a time per process; on Cloud Run request-billing CPU may be throttled after the response, so it can be slow until `--no-cpu-throttling`). Each chunk (200 docs) moves in a transaction that re-reads its documents: one that changed since the candidate scan (undeleted, edited, reparented) stays, with everything beneath it, until the next run; the move bumps rev. A 15-minute lease (`lease_until`) is claimed in a transaction so one instance runs it; `last_success` is written only after the run succeeds, so a failure releases the lease and a later read retries. A naive stored timestamp is read as UTC. Archiving also deletes the todos' images from the bucket, and the run ends with `sweep_orphan_blobs` (deletes blobs over an hour old that no todo lists) ([attachments](attachments.md)). Archived todos leave Trash and can't be restored from the UI. See [Firestore](../data/firestore.md).
- **Tree cache:** `get_tree` reuses its result while rev is unchanged.
- **Clear completed and types:** a `list`/`project` is cleared when everything beneath it is done and it holds at least one todo; its own `done` is ignored ([item types](item-types.md)).
