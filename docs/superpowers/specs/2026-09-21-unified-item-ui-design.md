# Unified item UI (type picker, item form, date picker) — design

Status: approved in chat 2026-09-21; implemented as app v81 (new-item sheet shows only the due-date group; the type popover in the composer is a list). Follows `2026-09-21-item-types-design.md`.
Delivered in four slices; each is deployable alone.

## Problem

The type registry (`app/types.json`, `Types.can/hasField`) generalizes behaviour, but the UI
does not:

- The `...` menu has one "Make X" item per other type (`render-node.js:214`). It grows with
  every type, never shows the current type, and reuses the pencil icon.
- Type can be changed in three different ways with different semantics: instant patch from
  the menu, deferred `<select>` in the edit sheet, and not at all at creation.
- "Add subtask" (`renderAddChildEditor`) is a hand-written form that ignores the registry.
  It always creates a `todo` and always shows a date, even under a project.
- The composer, add-subtask, split and edit sheet each handle due dates differently
  (composer: Today/Tomorrow/Pick chips; edit: date input + Today/Tomorrow/Clear chips +
  time; add-subtask: bare date + time; split: none).
- The edit sheet wires field groups by index (`extra.nodes.slice(2*i, 2*i+2)`), which breaks
  as soon as a type gains a field.
- Wording says "subtask" even under a list or project.
- Switching a todo to a list silently removes it from Next Up and the badge.

## Decisions

- **One `TypePicker`** built from `Types.names`; used by the menu, edit sheet, new-item
  sheet and composer. Types are never enumerated in feature code.
- **One `ItemForm`** for create (root or child) and edit. Inputs come from the registry's
  `fields`, keyed by field name.
- **One `DatePicker`** (chips + native input + time) used wherever a due date is entered.
- **Default type for a new item is sibling-first**, at the top level and under any parent
  (see below).
- **No nesting restrictions** (unchanged). No `childTypes`.
- **Split stays date-free and type-default** (bulk tool; uses the same default rule, no
  per-item controls).
- **Type change from the `...` menu is instant, with an Undo toast**; from a sheet it is
  applied on Save.
- No dark-mode work (out of scope, per project preference).

## Default type for a new item

Resolved on the client at the moment the sheet or composer opens:

1. The `type` of the **most recently created** non-deleted sibling under the target parent
   (root items are the "siblings" for the composer). "Most recently" = latest `create_date`;
   a type edited afterwards does not change the answer.
2. Otherwise the parent's registry `defaultChildType`.
3. Otherwise `todo`.

Unknown or missing stored types resolve to `todo` (existing `Types.nameOf` behaviour).
The resolved type is always shown in the type chip, so it is never a surprise, and one tap
overrides it. New registry key: `defaultChildType` per type (all `todo` today); it is only
used when there are no siblings.

Pure function `Types.defaultChildType(parent, siblings)`; no DOM, tested under `node --test`.

## TypePicker

`web/types-ui.js`: `TypePicker({ value, onChange })` returns a DOM node.

- Options come from `Types.names`; each shows registry `icon`, `label`, and a new one-line
  `description` (added to `types.json`).
- <= 4 types: a chip/segmented row. > 4 types: a button that opens a list sheet. No search
  until there are ~8 types. Optional registry `category` is reserved, not built.
- Row icon for non-checkbox types comes from the registry (no per-type strings in
  `render-node.js`); `list` and `project` get semantic icons in place of `grip`/`copy`.
- Menu: replace the N "Make X" items with a single entry **"Type: <Label> ›"** that opens
  the picker. Choosing a type applies at once and shows the toast **"Now a <Label> · Undo"**
  using the existing toast/undo path (`patch` with the previous `type`; the outbox already
  merges adjacent patches).

## ItemForm

`web/item-form.js`: `ItemForm({ mode: "create" | "edit", parent?, todo?, type? })`.

- Header: title input, then the type chip (`TypePicker`), then the field groups for the
  current type. Changing the type re-shows/hides groups immediately; hidden fields are kept,
  not cleared (existing rule).
- Field groups render from a registry-keyed map in `fields-ui.js`:
  `{ due_date, repeat, color, links, blocked_by, references }` → `{ node, read() }`. The
  positional `slice` wiring in `renderEditEditor` is removed. Adding a field to a type is
  a `types.json` edit plus, only for a brand-new kind of input, one renderer.
- `due_date` and `repeat` are one "When" group (date picker, then repeat).
- create mode: default type per the rule above; submit enqueues `create` (root) or a
  `split` of one description (child), both now carrying `type`. Only fields the chosen type
  has are sent.
- edit mode: initial values from the stored item; submit enqueues one `patch`, containing
  `type` only if it changed, and only changed fields (existing `Fields.patchPayload`).
- Replaces `renderAddChildEditor` and the body of `renderEditEditor`. `renderSplitEditor`
  is unchanged apart from wording and the default type.
- The viewer always shows a "Type" row (today only non-checkbox types do).

## DatePicker

`web/date-picker.js`: `DatePicker({ value, time, compact, onChange })`.

- Parts: chip row **Today, Tomorrow, Pick date, Clear**; the native date input with the
  existing "Pick a date" empty hint; the time field, enabled only when a date is set.
- One value model (`YYYY-MM-DD` plus optional time), combined via `Due.combine`. Chip
  highlighting derives from the value (Today / Tomorrow / custom date shown on Pick).
- `compact` (composer): chips hidden behind the calendar button, as today. Non-compact
  (sheets): chips always visible.
- Replaces the composer's inline chip code (`composer.js`), the edit sheet's shortcut chips
  (`editors.js`), and the bare inputs in add-subtask.
- Tapping the active Today/Tomorrow chip clears it (composer's current behaviour) everywhere.

## Composer

- Adds a type chip next to the calendar button showing the resolved default type
  (sibling-first over root items); one tap opens `TypePicker`. Quick path is unchanged:
  type a title, press enter, get the default.
- Changing the type in the composer applies to the next item only; the default is
  re-resolved after each create.
- Uses `DatePicker` in `compact` mode.

## API and sync

- `TodoCreate.type: ItemType | None` (default `todo`) and `TodoSplit.type: ItemType | None`
  (applies to every child created by that split; default `todo`). Unknown value → 422.
  Additive, no migration; old clients omit it and get `todo`.
- `sync.js`: `create` and `split` optimistic apply set `type` on the new node
  (`newNode` gains a `type` argument); request bodies include `type` when set. The `patch`
  path is unchanged.
- Server create/split write `type` through the existing `todo_to_doc` field map.

## Wording

"Add subtask" → "Add item"; "Split into subtasks" → "Add several"; sheet title
"New subtask" → "New item"; composer/aria labels say "item". Tests and OKF text that quote
the old strings are updated.

## Delivery

1. **DatePicker.** Composer, edit sheet and add-subtask adopt it. No API change.
2. **TypePicker + menu entry + Undo toast + viewer Type row.** Includes registry
   `description`/icons. No API change.
3. **ItemForm + sibling-first default + composer type chip + API `type` on create/split.**
   The largest slice; removes `renderAddChildEditor` and the index-based field wiring.
4. **Wording cleanup.**

Each slice updates `docs/okf/` (features, api/routes for slice 3, log) in the same commit
and bumps the app version, per project rules.

## Testing

- `node --test`: `Types.defaultChildType` (sibling-first, most-recent-wins, no siblings →
  registry default → `todo`, unknown type → `todo`, deleted siblings ignored); DatePicker
  value/chip-state logic (pure parts); optimistic `create`/`split` apply carries `type`;
  field-map renderer covers every field named in `types.json`.
- Python: `create` and `split` accept `type`, default to `todo`, reject unknown values;
  round-trip through `todo_to_doc` / `doc_to_todo`.
- Manual (Chrome, mobile width): menu length is constant as types are added (temporarily add
  a fourth type to `types.json`); type change → Undo restores the previous type; date chips
  behave identically in composer, new-item and edit; composer type chip resolves from root
  siblings.

## Out of scope

Child-type restrictions, per-item dates in Split, dark mode, picker search, `category`
grouping, new item types (this makes adding them cheap; it doesn't add any).
