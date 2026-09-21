---
type: Feature
title: Item types
description: Every todo has a type (todo, list, project); a shared registry says what each type can do.
resource: app/types.json
tags: [types, registry, data]
timestamp: 2026-09-21T07:15:00Z
---
Every row is a typed item: `todo` (today's behaviour), `list` (flat group header) or `project` (container that will show a progress readout). `Todo.type` ([Todo](../data/todo.md)) defaults to `todo`; a document with no or an unknown `type` reads as `todo` (server `doc_to_todo`, client `Types.get`), so there is no migration and an old cached client stays safe. New documents write `type: "todo"`.

**Registry (single source).** `app/types.json` declares, per type, the editable `fields` and the capability flags `hasCheckbox`, `appearsInNextUp`, `triggersAutodone`, `countsInBadge`, `showsProgress`, `notifies`. Python reads it through `app/types.py` (`can(item, flag)`, `can_type`, `has_field`); `scripts/gen_types.py` generates the checked-in `web/types-data.js`, wrapped by `web/types.js` (`Types.can`, `Types.hasField`). `tests/test_item_types.py` fails when the generated file is stale (run `python scripts/gen_types.py`). Feature code asks a flag; it never compares a type name.

**Rules.**
- A container (`hasCheckbox: false`: `list`, `project`) **ignores its own `done` everywhere**; completion is derived from the todos inside it.
- Switching type is an ordinary content edit (`PATCH /todos/{id}` with `type`, `If-Match`, outbox, [sync](sync-model.md)) that changes only `type`: `due_date`, `repeat` and `done` stay in the document, inactive, so switching back restores them.
- [Next up](next-up.md) walks through containers but lists only `appearsInNextUp` types; a container's dormant due date is not inherited by its children; a todo whose only open descendants are empty containers is itself a leaf; a container is never an open blocker (also the derived `blocked` flag).
- [Push reminders](push-reminders.md) (digest, heads-ups, `run_heads_up`) and the [calendar feed](calendar-feed.md) require `notifies`.
- [Clear completed](trash-archive.md): a container is cleared when everything beneath it is done and it holds at least one todo (server `clear_completed` and client `clearableIds`).
- Badge counts only `countsInBadge` types; [auto-done](auto-done.md) passes through containers (never completes one) and completes a todo parent when every todo beneath it is done.
- No nesting restrictions: any type may parent any type.

**Status.** Slice 1 (registry, data model, guards) is live. Not yet: the row without a checkbox, the Type picker in the `...` menu and edit sheet, the dynamic edit sheet, creating a non-todo from the composer, and the project progress readout (`done/total` over all descendant todos). Design: `docs/superpowers/specs/2026-09-21-item-types-design.md`.
