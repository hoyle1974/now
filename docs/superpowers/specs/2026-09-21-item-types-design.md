# Extensible item type system — design

Status: approved in chat 2026-09-21. Delivered in three slices.

## Goal

Every row is a typed item. Types: `todo` (today's behaviour), `list` (flat group
header), `project` (container with a progress readout). Behaviour differences come
from a declarative registry, never from `if type === "todo"`.

## Decisions

- **Container completion:** `list` and `project` ignore their own `done` everywhere.
  A retained `done` never affects Next Up, badge, autodone, clear-completed or blocking.
- **Shared registry:** `types.json` is the single source. `scripts/gen_types.py`
  generates a checked-in `web/types-data.js`; a test fails when it is stale.
  `web/types.js` wraps that data and adds per-type row/edit-sheet renderers.
  `app/types.py` loads the same JSON.
- **Storage:** `Todo.type` is `Literal["todo","list","project"]`, default `"todo"`.
  Reads use `.get("type", "todo")` (no migration); new docs write `type: "todo"`.
- **Switching type** patches only `type`. `due_date`, `repeat`, `done` are never touched.
- **Nesting:** no restrictions in v1 (any type may parent any type).
- **Composer:** creates `todo` only; items are converted afterwards. Revisit later.
- **Colors:** any root item gets a random colour at creation (unchanged).
- **Unknown `type` on the client** renders as `todo` (old cached clients stay safe).

## Registry

(As built: `todo` also has `showsProgress`, so its subtask chip is governed by the flag like a project's; the registry also carries `label` and `icon`.)

Per type: `fields` (editable inputs) and flags `hasCheckbox`, `appearsInNextUp`,
`triggersAutodone`, `countsInBadge`, `showsProgress`, `notifies` (push, Cloud Tasks
heads-ups, ICS feed).

## API

`TodoUpdate.type` (Literal; unknown value -> 422). `sync.js` `PATCH_FIELDS` gains
`type`. Ordinary content edit: `If-Match`, outbox, `txn_log`.

## Capability guards

Server:
- Next Up: `walk()` descends through containers but emits only where `appearsInNextUp`;
  an empty container never becomes a leaf.
- Push digest, heads-ups, ICS: additionally require `notifies`.
- `clear_completed`: a container is complete when it has >=1 `todo` descendant and all
  are done; its own `done` is ignored; an empty container is never cleared.
- `blocked_by`: a container is never an open blocker.
- `spawn_next_occurrence`: copies containers, preserving `type`.
- `todo_to_doc` / `doc_to_todo` carry `type` (explicit field maps).

Client:
- Badge `dueCount` filters on `countsInBadge`.
- Autodone skips containers (neither completes nor blocks); completes only `todo`
  parents when all their `todo` descendants are done.
- Row: no checkbox when `hasCheckbox` is false; done-sink ignores containers.

## Progress (project)

`done/total` over all descendant `todo`s at any depth; nested containers are not
counted; zero `todo`s shows nothing. Client-side, display only. `list` shows none.

## UX

Type picker in the `...` menu and in the edit sheet. The edit sheet renders inputs
from the target type's `fields`; inactive fields are hidden, not deleted. No notice
when data is hidden (single user).

## Delivery

1. `types.json`, generator + stale test, `Todo.type`, PATCH field, `app/types.py`,
   `web/types.js` with `todo` only, all capability guards.
2. `list` and `project`, both type pickers, dynamic edit sheet.
3. Progress readout.

Each slice is deployable alone and updates `docs/okf/` (data/todo, features/next-up,
features/auto-done, api/routes, log) in the same commit.

## Testing

Python: Next Up, push, ICS, clear_completed with containers; stale-generated-file test.
`node --test`: Autodone, Badge with containers; unknown type renders as todo.
