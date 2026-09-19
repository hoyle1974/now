# Optimistic edits with an outbox sync layer — design

## Goal

Cut perceived latency of every action. Today each action awaits a server round trip and then refetches the whole tree (`loadAndRender()`), so the UI changes only after two sequential requests, and a failed request loses the edit. Instead: apply each edit locally at once, queue it, and sync in the background with retry.

## Scope and assumptions

- One user, possibly on several devices (Mac, phone). No live sync between devices; a refresh pulls remote changes.
- Per-node versions detect stale writes.
- Pending edits survive reloads and lost signal (IndexedDB).
- Approach: keep the existing per-action REST endpoints and add `X-Txn-Id` / `If-Match` headers. No batch endpoint. Single-flight outbox, kept short by coalescing.

## 1. Server

**Versions**
- `TODO_ITEMS.version INTEGER NOT NULL DEFAULT 1`, added by a migration in `db.init()` like the existing `deleted` migration. `models.Todo` gains `version`.
- Every write bumps `version` on each row it touches: the target, plus all descendants for subtree ops (done-cascade, delete, undelete).
- `move` bumps only the moved node. Sibling `order_idx` compaction does not bump siblings (order is not content; bumping would cause false stale errors).

**Conditional writes**
- `PATCH`, `DELETE`, `undelete`, `split`, `move`, `parent` accept `If-Match: <version>`.
- Mismatch returns `409` with the current `Todo` as the body. Missing row returns `404`.
- No header means an unconditional write, so existing tests and curl usage keep working.

**Idempotency**
- Mutating endpoints (including `POST /todos` and `/split`) accept `X-Txn-Id`.
- New table `TXN_LOG(txn_id PRIMARY KEY, status, response_json, created_at)`. It is written in the same SQLite transaction as the mutation. A retry with a known txn returns the stored status and body without re-applying. Success and `409` outcomes are both stored.
- The txn ID is never stored on a todo row. Rows older than about 24 hours are pruned on startup.
- The server still assigns `todo_id` (and child IDs on split).

**Response shape**
- Mutating responses return the updated `Todo` with its new `version`.
- Split and subtree ops also return `affected: [{todo_id, version}]`, including new children with real IDs, so the client can update cached versions and replace temp IDs without a refetch.

## 2. Client store, outbox, persistence

**Store and render**
- `lastTodosById` / `lastRoots` become the live local model and the source of truth for rendering.
- Each action calls `applyLocal(op)`: mutate the local model, re-render immediately, enqueue the op. Actions do not await the network and no longer call `loadAndRender()`.
- `fetchTree()` runs only on page load and explicit refresh. Refresh waits for the outbox to drain first.
- Optimistic side effects run locally: done-cascade (already UI-only), the delete undo toast, and split/add creating local items with temp IDs (`tmp:<uuid>`).

**Outbox**
- Ordered list of `{txn_id, kind, target_id, base_version, payload, state, attempts}`. `kind`: `create`, `patch`, `delete`, `undelete`, `split`, `move`, `reparent`.
- Coalescing applies only to ops not yet sent:
  - consecutive `patch` ops on one target merge field by field, later values win;
  - a `patch` on an item whose `create` is unsent folds into the create payload;
  - an unsent `create` followed by a `delete` of that item cancels both.
- Persisted to IndexedDB on each enqueue and state change, and reloaded on startup. The local model itself is not persisted.
- On reload with a non-empty outbox: fetch the tree, replay pending ops onto it locally, then drain.

**Temp IDs and versions**
- On a `create` / `split` response, the client rewrites `target_id` and `base_version` on all later outbox ops and in the local model from `affected`. Strictly ordered, single-flight sending means no op goes out with a stale temp ID.
- Each local node keeps its last known server `version`. `base_version` is read when the op is sent, not when it is enqueued.

## 3. Sync loop, retry, conflicts

**Loop**
- One worker sends the head op with `X-Txn-Id` and `If-Match`. It wakes on enqueue, the `online` event, page visibility, and a backoff timer. A failed head blocks the ops behind it, since later ops may depend on it.

**Failure handling**

| Outcome | Action |
|---|---|
| Network error, timeout, 5xx, 429 | Retry with the same txn ID; backoff 1s doubling to a 30s cap, with jitter |
| 2xx | Merge response, update versions, remap IDs, pop op, persist |
| 409 | Conflict path |
| 404 | Drop the op and later ops on that target; remove the item locally; notify |
| Other 4xx | Drop the op; rebuild local state from the server; show an error naming the action |

**Conflict path (409 body = current server node)**
1. Update the local node's version and content from the server copy.
2. If the op touches fields the server copy did not change, rebase and retry with the new `base_version` and a fresh txn ID.
3. If the same field changed on both sides, **local wins**: retry the op on the new version.
4. Subtree ops (delete, split, done-cascade) do not rebase. On 409 refetch the whole tree and notify ("Changed on another device; reloaded").
5. Cap of about 3 conflicts per op; after that, treat as the bad-op case.

**Visibility**
- Status indicator: Synced / Syncing (n pending) / Offline / Error. It replaces the 5-second banner for network problems. Permanent failures stay until dismissed.

## Testing

- Server (pytest): version bumps including subtrees, `409` bodies, `404`, txn replay (including a replayed `409`), `affected` lists, migration on an existing `todo.db`.
- Client: extract outbox, coalescing, rebase and ID-remap into a DOM-free JS module tested with a fake fetch, including "response lost, retry, no duplicate", temp-ID rewrite across a chain of ops, reload replay, and conflict rebase with local-wins.

## Out of scope

Live multi-device sync, batching endpoint, subtree rebase, persisting the local model.

## Firestore implementation notes (this repo)

The sections above were written against SQLite; `now` runs on Firestore, so the server half differs:

- **Transactions instead of a lock.** Cloud Run can run several instances, so an in-process lock can't protect the version check. `db.run_atomic(txn_id, fn)` runs each mutating request in one Firestore transaction covering the `If-Match` check, the writes, and the `txn_log/<txn_id>` record. Firestore requires all reads before any write, so the db functions read first and return the updated todo (with its new `version`) instead of re-reading it.
- **Versions** live on each `todos` document. Documents written before this feature have no `version` field and read as `1`; their first write stores `2`.
- **`txn_log`** documents hold `{status, response_json, created_at}`. They are pruned on startup after 24 hours (`db.prune_txn_log`).
- **Root ordering:** roots have no `order_idx` and Firestore returns them by random document id, so roots are sorted by `create_date`. That keeps a new todo where the optimistic UI put it after a refresh.
- **Reparenting** a todo to a parent that doesn't exist now returns 404 (SQLite got this from a foreign key).
- **The SQLite backend has since been removed**; Firestore is the only backend.
- **Testing** runs against the Firestore emulator only: `scripts/test.sh` (pytest) and `scripts/e2e.sh` (sync engine vs. the running app). `conftest.py` refuses to run without `FIRESTORE_EMULATOR_HOST`, since this machine has real credentials.

## Detecting writes from other windows

Single user, several windows/devices; no fast updates wanted, and no background traffic.

- **Revision counter:** Firestore doc `meta/rev` (`{value}`), bumped inside every transaction that actually writes todo data (not for 409s, replays, 404s, or reads). `run_atomic` returns `(status, body, prev, rev)` and the API sends `X-Rev-Prev` / `X-Rev` headers; the txn_log record stores both so a replay answers identically.
- **Cheap check:** `GET /todos/rev` reads one document. `GET /todos/tree` includes `rev`, read *before* the tree so it can only be older than the data (worst case one redundant refresh, never a missed change).
- **Gap detection:** a write response whose `X-Rev-Prev` is ahead of the client's known revision means another window wrote in between; the client marks itself stale.
- **Triggers, no timers:** `focus`, `visibilitychange` (to visible), `pageshow` (persisted) and `online`, debounced to one server check per 30s to absorb flicker. The debounce is bypassed when already known stale, when the window was away 5s+ (tracked via blur/hidden timestamps), and on `online`. A failed check does not count as a check and is retried after 2s and 6s while the page is visible (a phone just woken from lock often has no network for a second or two); it never becomes a timer-driven poll. Mobile relies on visibility/pageshow because `focus`/`hasFocus()` are unreliable there. A hidden or unfocused window sends nothing.
- **Never clobber local work:** the refresh waits until the outbox is empty and no inline editor/input in the list is active, then re-downloads the tree and re-applies unsent ops (`rebuild`). It is retried when the outbox drains or the editor closes.
- **Cost:** one document read per check, plus one small extra write per edit (the counter).
- **Code:** `web/freshness.js` (policy, DOM-free, `tests_js/freshness.test.js`), revision tracking in `web/sync.js`, wiring in `web/app.js`.
- **Status pill:** shows the outbox state (Syncing / Offline / Sync error) or, when the outbox is empty, the freshness phase: Checking for changes… / Updating… / Reconnecting… / Updates waiting (held back by an open editor) / Couldn't check for updates / Synced. Transient phases are held for at least 0.8s so they can be read.
- **Event log:** `web/eventlog.js` is a persisted ring buffer (localStorage, 300 entries) fed by `onLog` hooks in the sync engine and freshness check plus page lifecycle listeners in `web/app.js`. It exists to see what a phone actually does on lock/unlock (which events fire, whether the network was up, how long the page was suspended). Titles are never logged. Shown via the "log" link (Copy / Clear / Close).
