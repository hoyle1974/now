---
type: Data Store
title: Firestore collections
description: Collections and documents used in Firestore.
resource: app/db_firestore.py
tags: [data, firestore]
timestamp: 2026-09-19T20:00:00Z
---
- `todos` — live and soft-deleted [todos](todo.md). Every tree read scans it, so it is kept small.
- `todos_archive` — todos deleted 30+ days ago with their subtrees ([archive](../features/trash-archive.md)).
- `txn_log` — outcome per `X-Txn-Id`, written in the same transaction as the write, for idempotent retries, pruned after 30 days at startup (must outlast the longest offline outbox) ([sync](../features/sync-model.md)).
- A single **rev** document, bumped by every data-changing transaction; `get_tree` caches its result while rev is unchanged.
