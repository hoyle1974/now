---
type: Data Store
title: Firestore collections
description: Collections and documents used in Firestore.
resource: app/db_firestore.py
tags: [data, firestore]
timestamp: 2026-09-19T00:00:00Z
---
- `todos` — live and soft-deleted [todos](todo.md). Every tree read scans it, so it is kept small.
- `todos_archive` — todos deleted 30+ days ago with their subtrees ([archive](../features/trash-archive.md)).
- `txn_log` — outcome per `X-Txn-Id`, written in the same transaction as the write, for idempotent retries, pruned after 30 days at startup (must outlast the longest offline outbox) ([sync](../features/sync-model.md)).
- `meta/archive` — `last_success` (set only after a sweep succeeds) and `lease_until` (15-minute lease taken in a transaction), so one instance sweeps per day and a failed run is retried.
- A single **rev** document, bumped by every data-changing transaction; `get_tree` caches its result while rev is unchanged.
- `push_devices` — one doc per installed device: `token`, `tz`, `platform`, `updated_at` ([push reminders](../features/push-reminders.md)).
- `push_sent` — sent-markers with `todo_ids` and `expires_at` (Firestore TTL). Also the `todos` composite index `done, deleted, due_date` for the due-window query.
