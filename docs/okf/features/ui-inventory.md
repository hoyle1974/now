---
type: Feature
title: UI feature inventory
description: Every user-facing capability and where to reach it; the checklist to run before shipping a UI change.
tags: [ui, checklist, regression]
timestamp: 2026-09-22T23:30:00Z
---
Rule (also in `CLAUDE.md`): a refactor must not silently drop anything on this list. When a capability is added or moved, update this file in the same commit; removing one needs the user's explicit yes. Run through it in Chrome ([local browser testing](../ops/local-browser-testing.md)) before deploying UI changes.

**Adding items**
- Composer (bottom bar): title, type chip (default = newest root item's type), due date chips (Today / Tomorrow / Pick date / Clear).
- Row menu `...` → **Add item** (New item sheet: title, type, due date and time) and **Add several** (one per line).

**A row**
- Checkbox (todos) / type icon (containers); swipe left to delete; long-press drag to reorder or re-parent; chevron to fold; progress chip, due chip, repeat chip, Blocked chip.
- Tap the row body → **viewer** (read-only): Type, Status, Due, Repeats, Subtasks n of m, Blocked; links, blocked-by, references (tap to jump); **Images** (add, view full size, remove); buttons Close and Edit. A `calendar` item's viewer also shows last-synced status (or the sync error) and a **Sync now** button that POSTs `/todos/{id}/sync` ([calendar sync](calendar-sync.md)).
- A **`calendar_event` row** (synced-in, [calendar sync](calendar-sync.md)) shows a repeat chip with the series' rule when it repeats (one row per series: its next occurrence). Its viewer shows When (start – end), Repeats, Location, Video call (Join call link), Guests (response summary and each guest's response) and Notes. The row is read-only: no checkbox, no swipe-to-complete, no drag/reorder; its Edit button is absent from both the row menu and its viewer, and Delete/Move/Type are absent from the row menu too — tap still opens the read-only viewer, and Copy with subtasks still works. A **`calendar` row** never shows Add item/Add several in its row menu and refuses a dragged-in child (its `calendar_event` children arrive only through sync, never a manual add) — see [item types](item-types.md).

**Row menu `...`**: Add item, Add several, **Edit**, **Type: X** (panel, applies at once, Undo), Copy with subtasks (outline to clipboard), Move up, Move down, Delete (Undo). Add item/Add several are left out under a `calendar` row; Edit/Type/Move/Delete are left out on a `calendar_event` row (both per [item types](item-types.md)'s `allowsUserChildren`/`editable` flags).

**Edit sheet** (from the menu or the viewer): title, type, due date + time with chips, repeat, color, links, blocked by, references, **Images** (upload is immediate, not tied to Save). Fields show per the type's registry `fields` ([item types](item-types.md)); a `calendar` shows only title, type, **Calendar URL** and color (links/references removed on request 2026-09-23).

**Lists and tabs**: Todos / Next up tabs ([next up](next-up.md)); pull to refresh; sync pill (Synced / Syncing / Offline / Sync error; tap to retry); summary line (open count, done today); done items sink.

**Search**: titles, links, colors, plus matches in the trash (opens the Trash page and that item, [trash](trash-archive.md)).

**Trash** (footer link): every trashed item incl. those inside a deleted parent, type icon, tap for read-only view, Undelete (restores the parent chain), Load more. **Clear N completed** (footer, Undo).

**More panel**: event log, reminders on/off, calendar feed (copy / subscribe) — **owner only**: the More panel shows no calendar link at all for any other signed-in email ([calendar feed](calendar-feed.md)), accent theme, completion sound, mascot (greets with overdue / due-today counts; his pupils glance around, follow phone tilt when shake is on, and look at where you tap him), shake, badge.

**Toasts**: Undo after delete / clear completed / type change; errors stay until tapped; "offline, couldn't load your list".

**Not in the UI on purpose**: dark mode (declined); images on the New item sheet (the todo must exist first).
