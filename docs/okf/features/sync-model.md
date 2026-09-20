---
type: Feature
title: Sync model
description: Optimistic local-first writes, outbox, idempotency, versions, freshness checks.
resource: web/sync.js
tags: [sync, client, core]
timestamp: 2026-09-19T20:00:00Z
---
Every action applies locally first and syncs in the background. Design spec:
`docs/superpowers/specs/2026-09-18-optimistic-sync-design.md`.

- **Outbox** (`web/sync.js`): ordered queue persisted in IndexedDB (`web/idb-store.js`); edits to the same item coalesce (only into an op never sent: a sent op may already be on the server, so a later edit or an undelete queues a new op); one worker sends in order, retry backoff 1s→30s.
- **Idempotency:** `X-Txn-Id` per op; server stores the outcome in `txn_log` in the write's transaction, kept 30 days so a long-offline device replays safely; `X-Txn-Id` must match `[A-Za-z0-9_-]{1,100}` and not be `__x__` (400 otherwise; clients send UUIDs) ([Firestore](../data/firestore.md)).
- **Versions:** writes send `If-Match: <version>`; stale → `409` + current todo. Field edits rebase (local wins per field); subtree ops reload.
- **New items:** temporary `tmp:` id; queued edits (target, `parent_id`, `blocked_by`, `references`) and model nodes are re-pointed on assignment, and `enqueue` resolves aliased tmp ids in those fields.
- **Freshness** (`web/freshness.js`): no timer. On focus / visible / `pageshow` / online / tapping the sync pill, one `GET /todos/rev`; tree re-downloaded only if rev moved. Debounced to 1 check per 30s, but an away ≥5s or just-online window always checks. On failure retries at 2s and 6s while visible. Refresh waits for the outbox to drain and any open editor to close. Pill states: *Checking for changes…*, *Updating…*, *Reconnecting…*, *Updates waiting*, *Couldn't check for updates*.
- **App version:** `/todos/rev` returns `version` from `APP_VERSION` in `web/app.js`, which must equal the `?v=` on assets in `web/index.html` (**bump both on release**). Mismatch → page reloads (holds during edits; once per target version via `sessionStorage`).
- **Collapse state:** `collapsed` patch skips `If-Match` and version bump (last write wins) but still bumps rev.
