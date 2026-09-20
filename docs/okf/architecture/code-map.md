---
type: Code Map
title: Code map
description: Where things live in the repository.
tags: [architecture, navigation]
timestamp: 2026-09-19T23:00:00Z
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
- `app.js` — main UI (incl. the todo viewer and edit sheets, see [fields](../features/fields.md)); holds `APP_VERSION` ([sync model](../features/sync-model.md)).
- `sync.js`, `idb-store.js` — outbox and IndexedDB persistence.
- `freshness.js` — remote-change checks. `eventlog.js` — [event log](../features/event-log.md).
- `reorder.js` — drag-drop → reparent ([ordering](../features/ordering-nesting.md)). `outline.js`.
- `due.js` ([due time](../features/due-time.md)), `autodone.js` ([auto-done](../features/auto-done.md)),
  `badge.js` (icon badge), `trash.js` ([trash](../features/trash-archive.md)),
  `fields.js` / `fields-ui.js` / `fields.css` ([fields](../features/fields.md)),
  `attachments.js` / `attachments-ui.js` ([attachments](../features/attachments.md)),
  `search.js` / `search-ui.js`.

**Other:** `scripts/` (test.sh, e2e.sh, scriptable-next-up.js, generate_icons.py),
`tests/` and `test_*.py` (python), `tests_js/` (node), `docs/superpowers/` (design specs).
