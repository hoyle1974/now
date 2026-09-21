---
type: Code Map
title: Code map
description: Where things live in the repository.
tags: [architecture, navigation]
timestamp: 2026-09-21T01:00:00Z
---
**Server (`app/`)**
- `main.py` — routes ([API](../api/routes.md)).
- `models.py` — pydantic models and limits ([Todo](../data/todo.md)).
- `db_firestore.py`, `db_firestore_helpers.py`, `db.py` — data layer, transactions, tree cache, archive sweep.
- `next_up.py` — ranking ([next up](../features/next-up.md)).
- `recurrence.py` — next-occurrence date maths ([repeating](../features/repeating-todos.md)).
- `push.py` — reminder planner and FCM sender ([push reminders](../features/push-reminders.md)).
- `ics.py` — iCalendar rendering ([calendar feed](../features/calendar-feed.md)).
- `auth.py` — Firebase token, widget token, Scheduler OIDC.
- `blobstore.py`, `attachments.py` — image bytes (GCS / in-memory) and type sniffing ([attachments](../features/attachments.md)).

**Client (`web/`)** — vanilla JS, no build step. `index.html` loads the scripts as classic scripts sharing one global scope, with `?v=` cache-busting ([sync model](../features/sync-model.md)).
- **Main UI**, ten parts loaded in this order: `app.js` (API, sync glue, todo actions; holds `APP_VERSION`), `ui-helpers.js` (panel state, icons, dates, row menu/meta), `row-interactions.js` (drag, long press), `render-node.js` (`renderNode`), `editors.js` (edit/split/add sheets and the viewer, see [fields](../features/fields.md)), `tree-view.js` (summary, `renderTree`, load, page lifecycle), `composer.js`, `next-up-ui.js` (tabs, Next up rows), `pull-refresh.js`, `more-panel.js` (event log, reminders, badge, look/mascot/shake). Order matters only for top-level statements; add a new part to `index.html` and to this list.
- **Sync:** `sync.js` (outbox), `idb-store.js` (IndexedDB), `freshness.js` (remote-change checks).
- **Domain helpers:** `due.js` ([due time](../features/due-time.md)), `autodone.js` ([auto-done](../features/auto-done.md)), `badge.js` (icon badge), `trash.js` ([trash](../features/trash-archive.md)), `fields.js` / `fields-ui.js` / `fields.css` ([fields](../features/fields.md)), `attachments.js` / `attachments-ui.js` ([attachments](../features/attachments.md)), `search.js` / `search-ui.js`, `reorder.js` (drag-drop → reparent, [ordering](../features/ordering-nesting.md)), `outline.js`, `eventlog.js` ([event log](../features/event-log.md)).
- **Platform:** `auth.js` (sign-in), `config.js` (git-ignored, from `config.example.js`; [forking](../ops/forking.md)), `push.js` + `sw.js` ([push reminders](../features/push-reminders.md); `sw.js` does no caching), `manifest.json`, `style.css`.
- **Look and feel:** `themes.js` (per-device accent themes, opt-in completion sound), `sparkle.js` (confetti on completion; no-op under reduced motion), `mascot.js` (idle mascot "Nudge", tinted by `--accent`).

**Client behaviours worth knowing**
- Toast (`#error`): `apiFetch` only clears an error it showed itself (`apiErrorShown`), never sync notices or the Undo toast; `claimToast` owns the shared element.
- The full-screen viewer/edit sheet owns one `history` entry (`syncHistory` in `ui-helpers.js`, `popstate` in `app.js`), so the back gesture closes or steps back.
- Mascot: taps on him are not activity; idle re-arm is throttled to 1s; the `devicemotion` listener is attached only while shake is armed, the page is visible and the mascot enabled. iOS forgets motion access on a full relaunch, so `now.shakeOn` is stored and re-requested on the first tap of the next session (event log line `re-armed on first tap`).

**Other:** `scripts/` (`test.sh`, `e2e.sh`, `init.sh`, `doctor.sh`, `create-bucket.sh`, `setup-push.sh`, `setup-calendar.sh`, `migrate-service.sh`, `lib/config.sh`, `scriptable-next-up.js`, `generate_icons.py`, `okf-reminder.sh`), `tests/` (python), `tests_js/` (node), `docs/superpowers/` (design specs and plans), `hosting-public/` (empty Firebase Hosting root; all traffic is rewritten to Cloud Run).
