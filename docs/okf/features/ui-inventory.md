---
type: Feature
title: UI feature inventory
description: Every user-facing capability and where to reach it; the checklist to run before shipping a UI change.
tags: [ui, checklist, regression]
timestamp: 2026-09-27T08:00:00Z
---
Rule (also in `CLAUDE.md`): a refactor must not silently drop anything on this list. When a capability is added or moved, update this file in the same commit; removing one needs the user's explicit yes. Run through it in Chrome ([local browser testing](../ops/local-browser-testing.md)) before deploying UI changes.

**Adding items**
- Composer (bottom bar): title, type chip (default = newest root item's type), due date chips (Today / Tomorrow / Pick date / Clear).
- Row menu `...` → **Add item** (New item sheet: title, type, due date and time; a **note** also gets the Markdown editor) and **Add several** (one per line).

**A row**
- Checkbox (todos) / type icon (containers); swipe left to delete; long-press drag to reorder or re-parent; chevron to fold; progress chip, due chip, repeat chip, Blocked chip.
- Tap the row body → **viewer** (read-only): Type, Status, Due, Repeats, Subtasks n of m, Blocked; links, blocked-by, references (tap to jump); **Images** (add, view full size, remove); buttons Close and Edit. A **note** shows its Markdown body under the title (no checkbox, no due date, no blocked-by). A `calendar` item's viewer also shows last-synced status (or the sync error) and a **Sync now** button that POSTs `/todos/{id}/sync` ([calendar sync](calendar-sync.md)).
- A **`calendar_event` row** (synced-in, [calendar sync](calendar-sync.md)) shows a repeat chip with the series' rule when it repeats (one row per series: its next occurrence). Its viewer shows When (start – end), Repeats, Location, Video call (Join call link), Guests (response summary and each guest's response) and Notes, plus a **Priority** select (High / Normal / Low) that applies at once. The row is read-only: no checkbox, no swipe-to-complete, no drag/reorder; its Edit button is absent from both the row menu and its viewer, and Delete/Move/Type are absent from the row menu too — tap still opens the read-only viewer, and Copy with subtasks still works. A **`calendar` row** never shows Add item/Add several in its row menu and refuses a dragged-in child (its `calendar_event` children arrive only through sync, never a manual add) — see [item types](item-types.md).

- A **shared item** ([sharing](sharing.md)): its root row shows a chip "Shared · can edit" / "Shared · read-only" (plus the owner's name when it isn't yours); every row inside it shows a small shared icon after the title; the viewer adds a **Shared** fact (Everyone can view / edit · whose). In a **read-only** share the checkbox is disabled, swipe right/left, double-tap rename, drag, Add item/Add several, Edit/Type, Move and Delete are not offered, and the viewer has no Edit button or image add/remove — tap to view, fold/unfold (your own view) and Copy with subtasks still work, and the root row still moves (Move up/down, drag), since where it sits is yours. Dragging an item into or out of a share asks first ("Everyone will see “x”." / "This removes “x” for everyone else."); drags a share doesn't allow are refused with a toast. Next up rows from a share show a "Shared" chip.

**Row menu `...`**: Add item, Add several, **Edit**, **Type: X** (panel, applies at once, Undo), Copy with subtasks (outline to clipboard), Move up, Move down, Delete (Undo). On a shared item's root the Delete entry reads **Remove from my list** when it isn't yours (only your list loses it; Undo toast "Removed from your list") and **Delete for everyone** when it is. Add item/Add several are left out under a `calendar` row; Edit/Type/Move/Delete are left out on a `calendar_event` row (both per [item types](item-types.md)'s `allowsUserChildren`/`editable` flags).

**Edit sheet** (from the menu or the viewer): title, type (a dropdown once there are more than four types), due date + time with chips, **Priority** (High / Normal / Low, on a todo), repeat, color, links, blocked by, references, **Images** (upload is immediate, not tied to Save). A **note** puts a tall Markdown editor (EasyMDE) under the type picker, then color, links and images; no due date, priority, repeat, blocked-by or references. Fields show per the type's registry `fields` ([item types](item-types.md)); a `calendar` shows only title, type, **Calendar URL** and color (links/references removed on request 2026-09-23).

**Lists and tabs**: Todos / Next up tabs ([next up](next-up.md)); pull to refresh; sync pill (Synced / Syncing / Offline / Sync error; tap to retry); summary line (open count, done today); done items sink.

**Search**: titles, links, colors, note bodies, plus matches in the trash (opens the Trash page and that item, [trash](trash-archive.md)).

**Trash** (footer link): every trashed item incl. those inside a deleted parent (except synced calendar events, which are never trashed: a deleted calendar comes back empty and re-syncs), type icon, tap for read-only view, Undelete (restores the parent chain), Load more. **Clear N completed** (footer, Undo).

**More panel**: event log, reminders on/off, calendar feed (copy / subscribe) — **owner only**: the More panel shows no calendar link at all for any other signed-in email ([calendar feed](calendar-feed.md)), accent theme, completion sound, mascot (greets with overdue / due-today counts; his pupils glance around, follow phone tilt when shake is on, and look at where you tap him), shake, badge.

**Toasts**: Undo after delete / clear completed / type change; errors stay until tapped; "offline, couldn't load your list".

**Not in the UI on purpose**: dark mode (declined); images on the New item sheet (the todo must exist first).
