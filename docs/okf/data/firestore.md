---
type: Data Store
title: Firestore collections
description: Collections and documents used in Firestore.
resource: app/db_firestore.py
tags: [data, firestore]
timestamp: 2026-09-27T02:00:00Z
---
Every collection below lives under a *partition*: `users/{email}/...` for a person's own
data, or `shares/{id}/...` for a shared subtree (same layout). `db.partition_ref()` builds
the parent document reference from `tenant.partition()` (`app/tenant.py`); `db.user_ref(email)`
always builds `users/{email}` (defaults to the signed-in user) and is used for per-person
data such as push devices and sent-markers, whatever partition is bound. The `users/{email}` parent documents never exist themselves — only
their subcollections — so listing them is done with `list_documents()`, not `stream()`.
Firestore paths and blob keys (`app/blobstore.py`, `{partition}/todos/{id}/{attachment}`) are both partitioned this way.

- `todos` — live and soft-deleted [todos](todo.md). Every tree read scans it, so it is kept small.
- `todos_archive` — todos deleted 30+ days ago with their subtrees ([archive](../features/trash-archive.md)).
- `txn_log` — outcome per `X-Txn-Id`, written in the same transaction as the write, for idempotent retries, pruned after 30 days at startup for every user (must outlast the longest offline outbox) ([sync](../features/sync-model.md)).
- `meta/archive` — `last_success` (set only after a sweep succeeds) and `lease_until` (15-minute lease taken in a transaction), so one instance sweeps per day per user and a failed run is retried.
- `meta/rev` — bumped by every data-changing transaction for that user; `get_tree` caches its result per user while rev is unchanged.
- `push_devices` — one doc per installed device: `token`, `tz`, `platform`, `updated_at` ([push reminders](../features/push-reminders.md)).
- `push_sent` — sent-markers with `todo_ids` and `expires_at` (Firestore TTL, 3 days). The
  TTL policy survives the `users/{email}/...` nesting because it is set with
  `--collection-group=push_sent` (`scripts/setup-push.sh`), which matches `push_sent` at any
  path depth, not just at the top level.

Index: `todos` composite `done, deleted, due_date` (`firestore.indexes.json`) for the reminders' due-window query. A per-collection-ID index applies to every `todos` subcollection regardless of path, so no change was needed for the `users/{email}/todos` nesting.
