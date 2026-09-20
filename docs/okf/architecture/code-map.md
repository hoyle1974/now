---
type: Code Map
title: Code map
description: Where things live in the repository.
tags: [architecture, navigation]
timestamp: 2026-09-20T20:00:00Z
---
**Server (`app/`)**
- `main.py` — routes ([API](../api/routes.md)).
- `models.py` — pydantic models and limits ([Todo](../data/todo.md)).
- `db_firestore.py`, `db_firestore_helpers.py`, `db.py` — data layer, transactions, tree cache, archive sweep.
- `next_up.py` — ranking ([next up](../features/next-up.md)).
- `recurrence.py` — next-occurrence date maths ([repeating](../features/repeating-todos.md)).
- `auth.py` — Firebase token + widget token.
- `blobstore.py`, `attachments.py` — image bytes (GCS / in-memory) and type sniffing ([attachments](../features/attachments.md)).

**Client (`web/`)**
- `themes.js` — per-device accent themes and the opt-in completion sound (`Themes`, `Sound`).
- `mascot.js` — the idle mascot "Nudge" (peek/blink/duck away; `Mascot`); tinted by `--accent`. Taps on him are not activity (they reach his click handler); idle re-arm is throttled to 1s; the `devicemotion` listener is attached only while shake is armed, the page is visible and the mascot enabled.
- Toast (`#error`): `apiFetch` only clears an error it showed itself (`apiErrorShown`), never sync notices or the Undo toast. Full-screen viewer/edit sheet owns one `history` entry (`syncHistory`/`popstate` in `app.js`) so the back gesture closes or steps back.
- `sparkle.js` — decorative confetti on completion / when everything is done (no-op under reduced motion).
- Main UI, split from one file into ten classic scripts that share one global scope and load in this order (`index.html`): `app.js` (API, sync glue, todo actions; holds `APP_VERSION`, [sync model](../features/sync-model.md)), `ui-helpers.js` (panel state, icons, dates, row menu/meta), `row-interactions.js` (drag, long press), `render-node.js` (`renderNode`), `editors.js` (edit/split/add sheets and the viewer, see [fields](../features/fields.md)), `tree-view.js` (summary, `renderTree`, load, page lifecycle), `composer.js`, `next-up-ui.js` (tabs, Next up rows), `pull-refresh.js`, `more-panel.js` (event log, reminders, badge, look/mascot/shake). Order matters only for top-level statements; add a new part to `index.html` and to this list.
- `sync.js`, `idb-store.js` — outbox and IndexedDB persistence.
- `freshness.js` — remote-change checks. `eventlog.js` — [event log](../features/event-log.md).
- `reorder.js` — drag-drop → reparent ([ordering](../features/ordering-nesting.md)). `outline.js`.
- `due.js` ([due time](../features/due-time.md)), `autodone.js` ([auto-done](../features/auto-done.md)),
  `badge.js` (icon badge), `trash.js` ([trash](../features/trash-archive.md)),
  `fields.js` / `fields-ui.js` / `fields.css` ([fields](../features/fields.md)),
  `attachments.js` / `attachments-ui.js` ([attachments](../features/attachments.md)),
  `search.js` / `search-ui.js`.

**Other:** `scripts/` (test.sh, e2e.sh, scriptable-next-up.js, generate_icons.py),
`tests/` (python), `tests_js/` (node), `docs/superpowers/` (design specs).
