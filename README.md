# now — A Personal Todo App

A minimal todo app built with **FastAPI** + a vanilla-JS frontend, backed by **Firestore** on GCP Cloud Run.

Designed as a learning project, but simple enough to actually use day-to-day.

## Stack

- **Backend:** FastAPI + Jinja2 (server-rendered HTML, no separate JS frontend)
- **Database:** Firestore (tests run against the emulator: `scripts/test.sh`)
- **Deployment:** Local dev → GCP CloudRun + Firestore

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Server runs at `http://localhost:8000`

## What's here

- `app/main.py` — FastAPI app with routes and Jinja2 templating
- `app/db.py`, `app/db_firestore.py` — Firestore data layer
- `templates/` — Jinja2 templates for UI
- `static/` — CSS/JS and other assets
- `web/` — Frontend JavaScript for drag-and-drop and interactions
- `scripts/` — Utility scripts
- `docs/` — Project documentation

## Sync model

Every action applies locally first and syncs in the background, so the UI
never waits on the network.

- **Outbox** (`web/sync.js`): edits become ops in an ordered queue, persisted
  to IndexedDB (`web/idb-store.js`) so they survive a reload. Repeated edits to
  the same item are coalesced; one worker sends them in order, retrying with
  backoff (1s doubling to 30s).
- **Idempotency**: each op carries `X-Txn-Id`. The server records the outcome
  in Firestore `txn_log` in the same transaction as the write, so a retry after
  a lost response replays the answer instead of applying twice.
- **Versions**: every todo has a `version`, bumped on each write. Writes send
  `If-Match: <version>`; a stale one gets `409` plus the current todo. Field
  edits rebase (local wins on the same field); subtree ops reload instead.
- **New items** get a temporary `tmp:` id until the server assigns the real one;
  queued edits are re-pointed automatically.
- **Changes from another window or device** are picked up when this window
  comes back into focus (or its tab becomes visible; `pageshow` on phones), or
  by tapping the sync pill. There is no timer: an unfocused or backgrounded
  window sends nothing. The check is one tiny `GET /todos/rev` (a single
  Firestore document, bumped by every data-changing transaction); the tree is
  re-downloaded only if the revision moved. Rapid flicker is debounced to one
  check per 30s, but a window that was away 5s+ (or that just came back
  online) always checks. If the check fails (a phone that just woke has no
  network yet) it retries after 2s and 6s while visible, then stops. The sync
  pill says what is happening: *Checking for changes…*, *Updating…*,
  *Reconnecting…*, *Updates waiting*, *Couldn't check for updates*. A write
  response also reveals a remote write (`X-Rev-Prev` ahead of what we knew). The
  refresh waits for unsent edits to drain and for any open editor to close, so
  it never wipes typed text.
- **App version:** `GET /todos/rev` also returns `version`, read at startup from
  `APP_VERSION` in `web/app.js` (the same number as the `?v=` on the assets in
  `index.html`; bump both together on a release). If it differs from the page's
  own, the page is running old code and reloads instead of refreshing, holding
  while an editor is open and at most once per target version (a
  `sessionStorage` guard) so cached code can't cause a reload loop.
- **Collapse state** is a `collapsed` field on each todo, patched through the
  same outbox and synced to every device. It is view state: a collapse-only
  patch skips the `If-Match` check and the version bump (last write wins, no
  conflicts with content edits) but still bumps the revision, so other windows
  notice it.
- **Ordering and nesting:** every todo, roots included, has an `order_idx` and is
  shown in that order. Every row has a drag handle. Dropping above or below a
  row moves the todo next to it; dropping on the middle of a row makes it that
  row's last subtask (`web/reorder.js` turns the drop into `{parent_id, index}`).
  It is one `reparent` op (`PATCH /todos/{id}/reparent`), applied optimistically
  like any edit; a move into the todo's own subtree is refused.
- **App icon badge:** the number of open todos due today or overdue
  (`web/badge.js`, Badging API). iOS needs notification permission first, so an
  "icon badge" link appears under the title until it is answered.

- **Event log** (the small "log" link under the title): a record, kept on the
  device (localStorage, last 300 entries), of what the page saw and did:
  visibility/focus/blur, `pageshow`/`pagehide`, `freeze`/`resume`, online/offline,
  each freshness check and its result, sends, retries, conflicts and tree loads.
  Newest first, with the gap since the previous entry (a big gap means the page
  was suspended). Copy puts it on the clipboard for pasting into a bug report.
  It records event names and short details only, never todo titles.

Design: `docs/superpowers/specs/2026-09-18-optimistic-sync-design.md`.

## Next up

The second tab lists the top 10 things to work on. `GET /todos/next`
(`app/next_up.py`) ranks open todos that have no open subtasks by: the earlier of
their own due date and their nearest due ancestor's, then their own due date, then
list order. The client only draws the answer. Tapping a row jumps to the list with
that todo scrolled under the finger.

## Tests

Tests only ever run against the Firestore **emulator** (needs Java and
firebase-tools); `conftest.py` refuses to run otherwise.

```bash
scripts/test.sh                    # python (server + firestore layer)
node --test tests_js/sync.test.js  # client sync engine
scripts/e2e.sh                     # engine vs. the running app + emulator
```

## Deploy

```bash
./deploy.sh    # gcloud run deploy now --source . --region us-central1
```

## Next: GCP Migration

This app will be deployed to GCP CloudRun with Firestore as the database using `zilch-gcp` for infrastructure automation.
