---
type: Feature
title: UI feature inventory
description: Every user-facing capability and where to reach it; the checklist to run before shipping a UI change.
tags: [ui, checklist, regression]
timestamp: 2026-09-21T23:00:00Z
---
Rule (also in `CLAUDE.md`): a refactor must not silently drop anything on this list. When a capability is added or moved, update this file in the same commit; removing one needs the user's explicit yes. Run through it in Chrome ([local browser testing](../ops/local-browser-testing.md)) before deploying UI changes.

**Adding items**
- Composer (bottom bar): title, type chip (default = newest root item's type), due date chips (Today / Tomorrow / Pick date / Clear).
- Row menu `...` → **Add item** (New item sheet: title, type, due date and time) and **Add several** (one per line).

**A row**
- Checkbox (todos) / type icon (containers); swipe left to delete; long-press drag to reorder or re-parent; chevron to fold; progress chip, due chip, repeat chip, Blocked chip.
- Tap the row body → **viewer** (read-only): Type, Status, Due, Repeats, Subtasks n of m, Blocked; links, blocked-by, references (tap to jump); **Images** (add, view full size, remove); buttons Close and Edit.

**Row menu `...`**: Add item, Add several, **Edit**, **Type: X** (panel, applies at once, Undo), Copy with subtasks (outline to clipboard), Move up, Move down, Delete (Undo).

**Edit sheet** (from the menu or the viewer): title, type, due date + time with chips, repeat, color, links, blocked by, references, **Images** (upload is immediate, not tied to Save). Fields show per the type's registry `fields` ([item types](item-types.md)).

**Lists and tabs**: Todos / Next up tabs ([next up](next-up.md)); pull to refresh; sync pill (Synced / Syncing / Offline / Sync error; tap to retry); summary line (open count, done today); done items sink.

**Search**: titles, links, colors, plus matches in the trash (opens the Trash page and that item, [trash](trash-archive.md)).

**Trash** (footer link): every trashed item incl. those inside a deleted parent, type icon, tap for read-only view, Undelete (restores the parent chain), Load more. **Clear N completed** (footer, Undo).

**More panel**: event log, reminders on/off, calendar feed (copy / subscribe), accent theme, completion sound, mascot (greets with overdue / due-today counts; his pupils glance around, follow phone tilt when shake is on, and look at where you tap him), shake, badge.

**Toasts**: Undo after delete / clear completed / type change; errors stay until tapped; "offline, couldn't load your list".

**Not in the UI on purpose**: dark mode (declined); images on the New item sheet (the todo must exist first).
