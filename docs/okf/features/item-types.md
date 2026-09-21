---
type: Feature
title: Item types
description: Every todo has a type (todo, list, project); a shared registry says what each type can do.
resource: app/types.json
tags: [types, registry, data]
timestamp: 2026-09-21T14:00:00Z
---
Every row is a typed item: `todo` (today's behaviour), `list` (flat group header) or `project` (container that will show a progress readout). `Todo.type` ([Todo](../data/todo.md)) defaults to `todo`; a document with no or an unknown `type` reads as `todo` (server `doc_to_todo`, client `Types.get`), so there is no migration and an old cached client stays safe. New documents write `type: "todo"`.

**Registry (single source).** `app/types.json` declares, per type, the editable `label`, `description`, `icon`, `defaultChildType`, `fields` and the capability flags `hasCheckbox`, `appearsInNextUp`, `triggersAutodone`, `countsInBadge`, `showsProgress`, `notifies`. Python reads it through `app/types.py` (`can(item, flag)`, `can_type`, `has_field`); `scripts/gen_types.py` generates the checked-in `web/types-data.js`, wrapped by `web/types.js` (`Types.can`, `Types.hasField`). `tests/test_item_types.py` fails when the generated file is stale (run `python scripts/gen_types.py`). Feature code asks a flag; it never compares a type name.

**Rules.**
- A container (`hasCheckbox: false`: `list`, `project`) **ignores its own `done` everywhere**; completion is derived from the todos inside it.
- Switching type is an ordinary content edit (`PATCH /todos/{id}` with `type`, `If-Match`, outbox, [sync](sync-model.md)) that changes only `type`: `due_date`, `repeat` and `done` stay in the document, inactive, so switching back restores them.
- [Next up](next-up.md) walks through containers but lists only `appearsInNextUp` types; a container's dormant due date is not inherited by its children; a todo whose only open descendants are empty containers is itself a leaf; a container is never an open blocker, and a container's own dormant `blocked_by` blocks nothing (neither the derived `blocked` flag, server and client, nor its children in the ranking); the blocked-by picker does not offer containers.
- [Push reminders](push-reminders.md) (digest, heads-ups, `run_heads_up`) and the [calendar feed](calendar-feed.md) require `notifies`.
- [Clear completed](trash-archive.md): a container is cleared when everything beneath it is done and it holds at least one todo (server `clear_completed` and client `clearableIds`).
- Badge counts only `countsInBadge` types; [auto-done](auto-done.md) passes through containers (never completes one) and completes a todo parent when every todo beneath it is done.
- No nesting restrictions: any type may parent any type.

**UI (app v81: one type control, one item form, one date picker).**
- A container row has no checkbox: the registry `icon` (`check`, `list`, `folder`) holds the slot; its own `done` never styles the row, and done-sink, swipe-to-complete, outline `[x]`, search marks and the open counts ignore it. A due date or repeat on a container shows no chip, is not "overdue", and does not sort.
- **Type picker** (`web/types-ui.js`, `TypeUI.create`): built from `Types.names`, a chip row up to 4 types, a described list beyond. Used by the edit and new-item sheets, the menu's Type panel and the composer. It keeps its value in a hidden input so an open sheet survives a re-render.
- **`...` menu** has one type entry, "Type: <label>", however many types exist; it opens a panel where a choice applies at once with an Undo toast ("Now a Project · Undo", `setType`/`showTypeUndo` in app.js). Menu order: Add item, Add several, Edit, Type, Copy, Move, Delete.
- **Item form** (`web/item-form.js`, `ItemForm.render`) is both the New item sheet (from Add item) and the Edit sheet: title, type picker, then one group per registry field the chosen type has (`FIELD_GROUPS`; `FieldsUI.renderEditFields` returns groups keyed by field). Fields the type lacks are hidden, not cleared, and are left out of the save. New item shows only the due date group; the rest is one Edit away.
- **Default type for a new item is sibling-first** (`Types.defaultChildType`): the type of the newest live sibling (by `create_date`), else the parent's `defaultChildType`, else `todo`. It applies under any parent and at the top level (composer). Add several uses the same default.
- **Composer:** a type chip beside the calendar button shows what the next item will be (resolved from the newest root item; a pick applies to one item only); a type without `due_date` hides the date button.
- **Dates:** `DatePicker` (`web/date-picker.js`) is the only date control: chips Today / Tomorrow / Pick date / Clear plus an optional time field, used by the composer, the new-item sheet and the edit sheet. Add several has no dates.
- The viewer always shows Type (Status too for checkbox types).

**Progress.** `Types.descendantCounts` counts only todos (checkbox types) at any depth, looking through containers; a project (and a todo with subtasks) shows the "n of m" ring chip when it holds at least one todo, a list shows none. Registry flag `showsProgress` is true for `todo` and `project`.

**Create.** `POST /todos` and `POST /todos/{id}/split` accept `type` (default `todo`, unknown → 422; split applies it to every child). A type without `due_date` ignores a supplied due date server-side (nothing is scheduled). Designs: `docs/superpowers/specs/2026-09-21-item-types-design.md`, `docs/superpowers/specs/2026-09-21-unified-item-ui-design.md`.
