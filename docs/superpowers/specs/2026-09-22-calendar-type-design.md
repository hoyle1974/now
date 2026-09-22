# Calendar item type — design

Status: approved in chat 2026-09-22.

## Goal

A `calendar` item type that syncs a live external ICS feed URL (e.g. a family
calendar's "secret address") into read-only `calendar_event` children, so
external calendar events show up in the same list as your todos. No new
scheduled job: sync is triggered by use (list load, manual button) and by the
existing daily digest job, and reuses the existing rev-bump/freshness
mechanism for clients to pick up changes.

## Types

- **`calendar`** — container. `hasCheckbox: false`, `appearsInNextUp: false`,
  `notifies: false`, `showsProgress: false`, `countsInBadge: false`.
  Fields: `title`, `calendar_url`, `color`, `links`, `references`,
  `attachments`. New flag **`allowsUserChildren: false`** (new registry flag;
  every other type defaults `true`).
- **`calendar_event`** — leaf. `hasCheckbox: false`, `appearsInNextUp: true`,
  `notifies: true`, `triggersAutodone: false`, `countsInBadge: false`,
  `showsProgress: false`. Fields: `title`, `due_date`, `location` (new field:
  free text, from ICS `LOCATION`, falling back to `DESCRIPTION` if empty).
  Server-written only via the sync task; no `blocked_by`/`repeat`/
  `attachments`.

New `Todo` fields, all server-managed / not user-editable:
- `external_uid` — stable ICS UID, set on `calendar_event`s, used to match
  across syncs.
- `last_synced_at`, `last_sync_error` — on the `calendar` item.

## Registry rule fix (required, not optional)

The existing "a due date on a container shows no chip, isn't overdue, doesn't
sort" behaviour is currently keyed off `hasCheckbox: false` client-side.
`calendar_event` is the first `hasCheckbox: false` type with a real, scheduled
`due_date`, so this has to be re-keyed off "type lacks the `due_date` field"
instead. Touches `web/ui-helpers.js` (`isOverdue`/`isUrgent`) and wherever the
list sorts by due date.

## Sync mechanism

No cron job. Staleness is checked wherever a `calendar` is read:

- **`GET /todos` / `GET /todos/tree`**: for each `calendar` in the result, if
  `last_synced_at` is null or older than **6 hours**, enqueue a Cloud Task
  (idempotent) and return the response immediately with whatever's cached —
  the request is never blocked on the external fetch.
- **Manual "Sync now" button** (in the calendar's own view): `POST
  /todos/{id}/sync` enqueues the same task directly.
- **Daily digest job** (`app/push.py`): while walking the tree, also enqueues
  this task for any stale `calendar` it finds, so push notifications don't go
  stale for a calendar nobody opens.

All three triggers call one shared `enqueue_calendar_sync(calendar_id)`
function — no duplicated enqueue logic.

**The task** (`POST /internal/sync-calendar/{id}`, Cloud Tasks OIDC auth, same
trust boundary as the existing digest/heads-up internal endpoints in
`app/tasks.py`):
1. Fetch the ICS URL (`icalendar` + `recurring-ical-events` for RRULE
   expansion).
2. Expand recurring events into individual occurrences within a rolling
   **60-days-ahead, no-past** window.
3. Diff by `external_uid` against existing `calendar_event` children: create
   new, update changed, delete ones no longer in the feed (full-replace
   reconciliation — the feed is always the source of truth).
4. Write through the normal todo create/update/delete path, so `/todos/rev`
   bumps normally.
5. On fetch/parse failure: leave existing `calendar_event`s untouched, set
   `last_sync_error`. `last_synced_at` is updated **even on failure**, so a
   persistently broken feed is retried once per staleness window, not on
   every list load.

**Client pickup:** no new mechanism. `calendar_event` writes bump
`/todos/rev` like any other write; the existing freshness poll
(`web/freshness.js`) picks it up on next focus/visible/online and reloads,
showing the normal "changes from another device" mascot note via
`remote-diff.js`.

## Enforcing `allowsUserChildren: false`

- **Server:** `POST /todos`, `/split`, and reparent/move reject (400) a
  `parent_id` pointing at a type with `allowsUserChildren: false`, unless the
  request is the internal sync task.
- **Client:** "Add item"/"Add several" hidden under a `calendar` row;
  drag-reparent and the blocked-by/move/reference pickers exclude `calendar`
  as a target.

## UI

- `calendar` gets its own icon, shows in the type picker like any type.
- Edit/new-item form gets a `calendar_url` field group (URL input). Empty is
  allowed (e.g. right after picking the type); sync no-ops until set.
- Opening a `calendar`'s view shows its `calendar_event` children as
  read-only rows (title, due date/time, location — no checkbox, no
  swipe-to-complete, no edit sheet), plus a header with `last_synced_at` /
  `last_sync_error` and a **Sync now** button (enqueues the task, shows a
  brief "Syncing…" state).

## API surface

- `POST /todos/{id}/sync` — normal user auth, `calendar` type only. Manual
  trigger.
- `POST /internal/sync-calendar/{id}` — internal only (Cloud Tasks OIDC).
  Does the actual fetch/diff/write.
- `POST /todos` / `/split` / reparent — extended to 400 on
  `allowsUserChildren: false` parent (non-internal caller).

## Client/server split

Sync logic is server-side: it must run with no client open (digest-triggered
resync) and reconcile atomically (diff-by-UID) regardless of which device
triggered it. Recorded in `docs/okf/architecture/client-server-split.md`
under "Server deliberately owns the logic."

## Testing

Python: registry flag tests (`allowsUserChildren`, both new types) in
`tests/test_item_types.py`; sync-diff logic against fixture ICS files
(add/update/delete-by-UID, recurrence expansion, all-day vs timed, malformed
feed); `allowsUserChildren` 400s on create/reparent/split; internal endpoint
auth; staleness threshold with injectable clock.

JS: type picker/ItemForm include `calendar_url` field group; "Add item"
hidden under a `calendar` row; `calendar_event` rows render without
checkbox/edit; regression test for the due-chip/sort fix (now keyed off
`due_date` field presence, not `hasCheckbox`) since it changes existing
`list`/`project` behaviour too.

Manual: `docs/okf/ops/local-browser-testing.md` checklist, extended with
adding a Calendar, watching Sync now populate events, and confirming
Add-item is absent under it.

## Delivery / OKF updates (same commits)

- New `docs/okf/features/calendar-type.md`, linked from `item-types.md` and
  `index.md`.
- `client-server-split.md`: record calendar sync as server-side (see above).
- `ui-inventory.md`: add Sync-now button / read-only event rows.
- `item-types.md`: mention the due-chip/sort re-keying and the new
  `allowsUserChildren` flag.
- `log.md` dated entry.
