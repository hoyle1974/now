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
- **Color, links, dependencies:** each todo has `color` (one of red, orange,
  yellow, green, teal, blue, purple, pink, or null), `links` (up to 20 of
  `{url, label|null}`, http/https only), `blocked_by` and `references` (lists of
  todo ids, up to 50). All are set via `PATCH /todos/{id}` (lists replace the
  whole value; `color: null` clears), are content edits (`If-Match`, version
  bump) and default to empty on older docs. Ids must exist and not be the todo
  itself (400 otherwise); `blocked_by` must stay acyclic (400). Ids of deleted
  todos are kept (trash is restorable) and simply ignored when computing
  `blocked`, a derived read-only boolean that `GET /todos/tree` (only) adds:
  true if any `blocked_by` todo is live and not done.
- **Ordering and nesting:** every todo, roots included, has an `order_idx` and is
  shown in that order. Every row has a drag handle. Dropping above or below a
  row moves the todo next to it; dropping on the middle of a row makes it that
  row's last subtask (`web/reorder.js` turns the drop into `{parent_id, index}`).
  It is one `reparent` op (`PATCH /todos/{id}/reparent`), applied optimistically
  like any edit; a move into the todo's own subtree is refused.
- **Due time:** `due_date` carries an optional time. A date-only due is stored as
  midnight and means all-day (overdue once its day ends); any other time makes
  it a timed due, overdue the moment it passes and shown as "Today 3:00 PM"
  (`web/due.js`). Next up ranks earlier times first within a day, with all-day
  counting as the end of the day.
- **Auto-done parents:** completing the last open subtask also completes its
  parent, upward (`web/autodone.js`, sent as ordinary queued edits). It is
  one-way: un-doing a subtask or adding one never reopens a parent.
- **Done rows sink:** within each group, done rows display below the open ones
  (each part keeps its stored `order_idx` order); a just-completed row waits for
  its animation before dropping. Display only.
- **Repeating todos:** a todo can repeat every N days, weekdays (Mon-Fri), weeks,
  months or years (`repeat: {unit, every}`, set in the edit sheet; needs a due
  date). Completing it queues a `POST /todos/{id}/repeat`, and the server
  clones the todo and its live subtasks in one transaction as the next
  occurrence: open, placed right after the original, with the next due date
  (`app/recurrence.py`: stepped from the due date, first one after today;
  month/year clamp to the month end; a due time is kept) and dated subtasks
  shifted by the same amount. The completed original stays as a done record.
  A todo spawns at most once (`spawned_id`), so unticking and re-ticking or two
  devices completing it never double-copy. The copy is not optimistic: the
  client reloads the tree when the server confirms it.
- **Parents and subtasks:** a row shows only its own `done`. Completing the last
  open subtask marks the parent done once (stored, upward); nothing ever
  reopens a parent, and checking a parent does not change its subtasks.
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
node --test tests_js/*.test.js     # client sync engine, trash
scripts/e2e.sh                     # engine vs. the running app + emulator
```

## Clear completed and Trash

- **Clear completed** (button under the list) is one outbox op,
  `POST /todos/clear-completed`: in a single transaction it soft-deletes every
  done todo whose whole subtree is done (only the topmost of each subtree is
  flagged, so undoing it restores the subtree). Done todos with unfinished
  descendants are kept. The toast has an Undo that queues an `undelete` per item.
- **Trash** (footer link) lists `GET /todos/trash` and restores with the normal
  `undelete` op. If an ancestor is also deleted, the todo is restored at the
  top level so it doesn't stay invisible. Code: `web/trash.js`.

- **Archive.** Todos deleted 30+ days ago, with everything beneath them, move from
  `todos` to `todos_archive` (`archive_expired` in `app/db_firestore.py`), so the
  collection every tree read scans stays small. Deleting stamps `deleted_at`; the
  sweep runs at most once a day, triggered by `/todos/tree` and `/todos/next`.
  Archived todos no longer appear in Trash and can't be restored from the UI.
- **Tree cache.** `get_tree` reuses its result while the `rev` counter is unchanged,
  so an unchanged list costs one Firestore read per request instead of one per todo.

## Lock Screen widget (iOS, Scriptable)

`scripts/scriptable-next-up.js` shows the Next up list on the iOS Lock Screen and
Home Screen through the free [Scriptable](https://scriptable.app) app.

The app's API needs a Firebase sign-in token that expires hourly, which a widget
can't refresh. Instead `GET /todos/next` (only that route, read-only) also accepts
an `X-Widget-Token` header matching the `WIDGET_TOKEN` env var on the Cloud Run
service (`app/auth.py`). Unset, the token is off.

1. Make a token and set it on the service (this is a secret; don't commit it):
   ```bash
   openssl rand -hex 24
   gcloud run services update now --region us-central1 --update-env-vars WIDGET_TOKEN=<token>
   ```
   Rotate it the same way, then update the script. Keep a local copy in
   `.scriptable-secret` (git-ignored).
2. In Scriptable, create a script, paste in `scripts/scriptable-next-up.js`, and
   set `TOKEN` to the token: exactly the token characters, nothing after the
   closing quote (a stray `.` or space gives "can't load").
3. Run it once in the app to check it. Then long-press the Lock Screen, Customize,
   add a Scriptable widget (rectangular: top 3), and choose the script under
   Script. On the Home Screen, small shows 4 and medium shows 6.
4. "Next up: can't load" means the request failed: check the token, the `BASE` URL
   in the script, and that the service is deployed. Test with
   `curl -H "X-Widget-Token: <token>" https://now-app.web.app/todos/next?limit=3`.

iOS decides when widgets refresh (the script asks for ~15 minutes), so the list
can lag a little.

## Image attachments

A todo can carry up to 10 images (JPEG, PNG, GIF, WebP, 10 MB each), added from
the todo's view sheet by picker, drag-drop or paste. Online only: nothing is
queued offline, and a todo that hasn't synced yet can't take images.

- **Bytes** live in a private Cloud Storage bucket (`<project>-attachments`,
  `us-central1`, public access prevention on, no CORS) under
  `todos/{todo_id}/{attachment_id}`. **Metadata** (`id`, `name`, `content_type`,
  `size`) is `Todo.attachments` in Firestore, so it rides the normal version and
  `If-Match` handling. The browser never talks to the bucket: uploads and
  downloads go through the authenticated API (`POST/GET/DELETE
  /todos/{id}/attachments[/{aid}]`), and images are shown as blob URLs.
- The server sniffs the file's leading bytes and ignores the client's type; SVG
  is refused. Downloads are `nosniff`, `inline`, and cached forever (an
  attachment never changes).
- Soft-deleting a todo keeps its images; the 30-day archive deletes them.
  Recurring todos don't copy images to the next occurrence.
- **One-time setup:** `scripts/create-bucket.sh` creates the bucket, grants the
  Cloud Run service account `objectAdmin` on that bucket only, and sets
  `ATTACHMENTS_BUCKET` on the service. Until it is set, Cloud Run refuses
  uploads instead of storing them in memory. Locally (no bucket) an in-memory
  store is used, so images vanish on restart.
- Code: `app/blobstore.py` (GCS and in-memory stores), `app/attachments.py`
  (type sniffing), `web/attachments.js` and `web/attachments-ui.js`.

## Deploy

```bash
./deploy.sh    # gcloud run deploy now --source . --region us-central1
```

## Next: GCP Migration

This app will be deployed to GCP CloudRun with Firestore as the database using `zilch-gcp` for infrastructure automation.
