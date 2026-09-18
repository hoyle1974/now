# UI Review — Task List

Source: manual UI review + live interaction with the running app (Sep 18, 2026),
covering add/check/split/delete flows on the hierarchical todo list at
`http://localhost:8000`. Frontend lives in `web/` (`index.html`, `app.js`,
`style.css`); backend is FastAPI + stdlib `sqlite3` in `app/`.

**This app will primarily run on mobile.** Design and test decisions from here
on should default to touch/small-viewport first, not desktop-with-a-mobile-
fallback — e.g. no hover-only affordances, ≥44px touch targets, verify on an
actual narrow viewport rather than just eyeballing desktop at 1400px.

Work through tasks in order — they're ranked by priority/impact. Check one off,
verify it in the browser, then move to the next. Update this file as tasks are
completed or as scope changes.

## Tasks

- [x] **1. Add parent/leaf visual distinction.** Right now a todo with 6
  children looks identical to one with none until you scroll past it. Add a
  chevron/expand-collapse affordance and/or a subtask count badge (e.g. "3
  subtasks") on any row that has children.
  Done: leaf rows get a hidden spacer where the chevron would go; parent rows
  get a ▼/▶ toggle button plus a pill badge showing total descendant count
  (`web/app.js` `renderNode`/`countDescendants`, `web/style.css`
  `.todo-toggle`/`.todo-count-badge`).

- [x] **2. Add collapse/expand for subtrees.** Deep nesting currently forces
  the full tree to render at all times — a list with a handful of split
  parents already runs 30-40+ rows. Add per-node collapse/expand (likely
  paired with task 1's chevron), defaulting to expanded or collapsed per your
  judgment.
  Done: same chevron toggles a `collapsedIds` Set in `web/app.js`; collapsed
  parents skip rendering their `<ul>` of children. Defaults to expanded
  (unchanged behavior until a user collapses something). Verified in browser:
  collapsing a 9-subtask node hides its subtree while siblings stay visible,
  and re-expanding restores it.

- [x] **3. Fix action-button layout at depth / on mobile.** Split/Delete
  buttons stay flush right regardless of indentation depth. At 4+ levels of
  nesting this is already tight on desktop and will wrap badly or crowd the
  edge on narrow viewports. Test at ~400px width.
  Done: added a `max-width: 480px` media query in `web/style.css` that gives
  `.todo-actions` `flex-basis: 100%` and drops `margin-left: auto`, so on
  narrow viewports the buttons wrap to their own line aligned with the row's
  own left edge (at whatever depth) instead of stranding at the far right
  with a dead gap. Desktop layout (buttons flush right) is unchanged.
  Verified by simulating a 400px-wide container in the browser at several
  nesting depths.
  Superseded by task 4: once actions move into a per-row menu, this wrapping
  fix becomes moot (no second line of buttons to wrap) — leaving the CSS in
  place is harmless but task 4's menu is the real fix going forward.

- [x] **4. Replace per-row Split/Delete buttons with a single "more actions"
  menu.** Rendering two (soon three, once task 10 lands) buttons on every row
  doesn't scale — it's the root cause of task 3's crowding and will only get
  worse as more per-row actions are added. Replace with a single kebab (⋮)
  icon per row that opens a small menu with Split, Delete, Edit title, and
  Set due date. Since this app is primarily used on mobile (no hover), the
  kebab should be always-visible and tap-to-open, not hover-revealed —
  hover-reveal is a desktop-only pattern and would make actions undiscoverable
  on a touch device. Put Delete inside the menu (not a bare top-level button)
  so it isn't a stray tap target next to Split. Aim for a ≥44px tap target on
  the kebab itself even though the icon glyph is small.
  Done: rows now show a single 44px-tap-target kebab (`.todo-kebab`) instead
  of the old Split/Delete buttons; tapping opens an absolutely-positioned
  dropdown (`.todo-menu-dropdown`) with Split and Delete (Edit title/Set due
  date to be added by task 10). Only one menu is open at a time
  (`openMenuTodoId` in `web/app.js`), a document-level click listener closes
  it on outside click, and the old `.todo-actions` CSS/media query from task 3
  was removed as dead code. Verified in browser: open/close, click-outside-
  close, Split still opens the inline editor, Delete still removes the item
  and updates subtask-count badges.
  Bug hit + fixed along the way: `.todo-menu-item`'s text was invisible
  (white-on-white) because Pico redefines `--pico-color` inside `<button>`
  for its filled-button look, so `color: var(--pico-color)` inside a button
  rule resolves to Pico's white, not the page text color — fixed by resetting
  `--pico-color` locally on `.todo-menu-item` before using it. Worth
  remembering for any future custom button styling against Pico.

- [x] **5. General mobile pass.** Beyond the menu consolidation in task 4,
  audit the rest of the UI for touch-friendliness on a real narrow
  viewport (~360-400px, e.g. a mid-range Android) rather than a shrunk
  desktop window: chevron/checkbox tap targets are currently small
  (~1.5rem) and close together — bump to ≥44px hit areas without blowing up
  visual size (padding trick, not just the glyph); confirm the add-todo
  input and its Add button are comfortably tappable and that the on-screen
  keyboard doesn't obscure the input when it's focused; confirm horizontal
  scrolling never appears at any nesting depth; re-check task 4's layout and
  task 8's typography scale actually read well at this width, not just in
  the simulated-container tests used so far.
  Done: chevron (`.todo-toggle`) and checkbox (now wrapped in a
  `.todo-check-hit` label) both get a 44px tap box while keeping their small
  visual glyph/checkbox size — no negative-margin trick (tried it, it made
  the checkbox visually collide with the title; reverted to plain sizing,
  which costs a little extra row height but is correct). `.todo-row` switched
  from `align-items: baseline` to `center` so the taller tap targets line up
  with the text. Added a `focus` listener on the add-todo input that
  `scrollIntoView`s it after a short delay, as a mitigation for on-screen
  keyboards covering it (can't fully verify without a real device). Verified
  no horizontal scroll at desktop width and via the 400px-container
  simulation at multiple nesting depths.
  Drive-by fix: removed leftover square `::marker` bullets on nested `<li>`s
  — Chrome's UA stylesheet resolves nested-list marker type per-`<li>`, so
  `list-style: none` on the parent `<ul>` didn't reach it; fixed by setting
  `list-style: none` directly on `.todo-node`. Not in the original task list
  but was actively colliding with the new taller rows.

- [x] **6. Make "done" cascade visually/functionally to children.** Checking
  a parent item currently does nothing to its subtree — children stay full
  brightness and interactive. Decide on behavior (e.g. dim/gray out children,
  or cascade the checked state) and implement it.
  Done: chose functional cascade over a purely visual dim, since a done
  parent implying done subtasks matches how todo apps (Things, Todoist)
  normally behave, and it gets the visual treatment (strikethrough / muted
  color) for free via the existing `.todo-title--done` styling — no separate
  "ancestor is done" CSS state needed. Cascades in both directions
  (completing a parent completes all descendants; un-completing it
  un-completes them too) for a consistent tree rather than partial state.
  Implemented server-side so it's correct regardless of client:
  `db.cascade_done`/`_cascade_done_recursive` in `app/db.py` walks the
  subtree in one transaction, called from `PATCH /todos/{id}` in
  `app/main.py` whenever `done` is part of the request body. Frontend needed
  no changes — it already does a full tree refetch after any toggle. Verified
  in browser (checking a 4-child parent checks all 4; unchecking reverts all
  4; an unrelated sibling is untouched) and `pytest test_main.py` still
  passes (11/11).

- [x] **7. Clarify where "New todo" adds items.** The top-level input always
  appends to the end of the flat list, with no way to add a new item directly
  under a specific parent except via Split (which requires committing to a
  full replace/append of that node's children). Consider adding an "add
  child" affordance per row, separate from Split — this can live in task 4's
  per-row menu alongside Split/Delete/Edit/Due date rather than as another
  bare button.
  Done: added an "Add child" entry (above Split) to task 4's kebab menu. It
  opens a lightweight single-line inline editor (`renderAddChildEditor` in
  `web/app.js`) rather than Split's multi-line textarea, and reuses the
  existing `POST /todos/{id}/split` endpoint with a one-item `descriptions`
  array — note the endpoint already only appends new children (it computes
  `next_order` from the current max and never touches existing rows), so no
  backend change was needed; the "full replace" read in the original task
  description was a misconception about Split's behavior, not something we
  had to fix. Verified in browser: adding a child to a node that already had
  4 subtasks left all 4 intact and added a 5th, badge count updated
  correctly.

- [x] **8. Add depth-based typographic hierarchy.** Every level currently
  shares the same font weight/size, so depth reads only from indentation.
  Add a subtle size/weight/color falloff per level to reinforce the tree
  structure at a glance.
  Done: `renderNode` in `web/app.js` now takes a `depth` param (0 at root,
  +1 per nesting level) and sets it as a `--depth` CSS custom property on
  each `<li>`. `.todo-title` in `web/style.css` uses `clamp()` over
  `calc(... - var(--depth) * step)` for font-weight, font-size, and opacity,
  so the falloff is continuous and self-limiting — very deep nodes stop
  shrinking at a readable floor instead of degrading indefinitely. Verified
  by building a synthetic depth-0..5 chain via the API and confirming the
  falloff reads clearly in the browser, then deleting that test chain.

- [x] **9. Reduce per-row date noise.** "Created Sep 18, 2026" repeats on
  every single row regardless of depth, which is a lot of low-value text at
  this density. Consider hover-only/detail-view display, or relative
  timestamps ("2h ago"). On mobile specifically, hover-only isn't viable —
  favor a detail view/expansion or just deprioritizing it visually (e.g.
  only on the deepest/leaf rows).
  Done: went with "only on leaf rows" — parent rows already carry the
  subtask-count badge from task 1, so repeating "Created ..." on every
  parent in a deep tree added little (hover-only was ruled out per the
  mobile-first note at the top of this doc). `web/app.js`'s `renderNode` now
  only builds the "Created ..." part of `.todo-meta` when `!hasChildren`;
  "Due ..." still always shows when set, since that one's actionable.
  Verified in browser: parent rows show just the badge, leaf rows still show
  their Created date.

- [x] **10. Allow editing a todo's title and due date.** There's currently no
  way to rename a todo or set/change its due date after creation — title is
  fixed at creation and due date is never set anywhere in the UI. Surface
  Edit title / Set due date as entries in task 4's per-row menu rather than
  more standalone buttons, with a lightweight inline editor (similar
  treatment to the Split editor) and a due-date picker. Note: the backend
  already supports title via `PATCH /todos/{id}` (`TodoUpdate.title` in
  `app/models.py`), but `TodoUpdate` has no `due_date` field and
  `update_todo` in `app/main.py` doesn't set it — extend both for due-date
  edits to work end to end.
  Done: combined "Edit title" and "Set due date" into a single "Edit" menu
  entry rather than two, since they're naturally edited together and it
  keeps the menu shorter — opens one inline editor
  (`renderEditEditor`/`saveEdit` in `web/app.js`) with a title text input
  (pre-filled) and a native `<input type="date">` (pre-filled from
  `due_date` when set). Backend: added `due_date` to `TodoUpdate` in
  `app/models.py`, wired it into `update_todo` in `app/main.py`, and into
  the `UPDATE` statement in `db.update_todo` (`app/db.py`) — previously that
  statement didn't even have a `due_date` column in its `SET` clause.
  Known limitation: clearing an existing due date isn't supported (an empty
  date input is just not sent, matching how title/done already can't be
  cleared through this endpoint) — acceptable for this scope, not worth a
  new "clear" affordance. Verified in browser: renamed a todo and set a due
  date, both persisted and the due date now shows in that row's meta line;
  `pytest test_main.py` still passes (11/11).

## Notes / non-issues worth preserving

- The Split flow (inline textarea, one item per line, Save/Cancel) works well
  and should be kept as the interaction pattern — don't replace it with a
  modal.
- Add/check/delete are all instant, no full page reload — keep that.
- Delete has no confirmation dialog. Flagged as a deliberate simplicity
  tradeoff for this toy project, not a bug — leave as is unless told
  otherwise.
