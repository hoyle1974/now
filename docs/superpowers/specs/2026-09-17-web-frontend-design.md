# Web Frontend Design

## Context

The app currently exposes a pure JSON API (`app/main.py`) over a tree-structured
todo model (`app/models.py`: `Todo` has `parent_id` / `child_ids`, plus a
`split` operation that turns one todo into several children). There is no
HTML-serving route; `templates/base.html` is an unused empty shell.

Goal: add a lightweight, JS-driven web frontend so todos can be viewed and
managed in a browser, without introducing a build step, a frontend
framework, or a backend rewrite.

## Architecture

Static frontend files live in a new `web/` directory and are served by
FastAPI's `StaticFiles(directory="web", html=True)`, mounted at `/`. The
frontend is a single page with no client-side routing. It talks exclusively
to the existing `/todos` JSON API via `fetch()`. Because the API and the
frontend are served from the same FastAPI process/origin, no CORS
configuration is needed.

`templates/base.html` and the Jinja2 setup in `app/main.py` are left as-is
(unused) — this design does not remove them, just doesn't use them for the
new frontend.

## File layout

```
web/
  index.html   — page shell: containers for the todo tree, add-form, error div
  app.js       — all fetch/render/event logic
  style.css    — custom tweaks on top of Pico.css (can start empty)
```

`app/main.py` gets one addition: mounting `web/` via
`app.mount("/", StaticFiles(directory="web", html=True), name="web")`.
This mount must be added *after* all `/todos` routes are defined, since a
mount at `/` would otherwise shadow them.

## Data flow — building the tree

The `Todo` model carries `child_ids` (a list of IDs) but not full child
objects, and there is no "get whole tree" endpoint. `app.js` builds the tree
client-side:

1. `GET /todos/root` to get root todos.
2. For each todo with non-empty `child_ids`, `GET /todos/{id}` for each
   child, recursively, until the whole tree is fetched.
3. Build a `Map<todo_id, todo>` from everything fetched, then run a
   recursive `renderNode(todo)` that creates the DOM for a todo and its
   children by looking up `child_ids` in the map.

This is an N+1 request pattern for a tree of N todos on every load. This is
an accepted, named inefficiency for this design — fine at personal-project
scale. No backend "tree" endpoint is added.

## Interactions

Every mutation follows the same pattern: call the relevant API endpoint,
then re-run a single `loadAndRender()` function that redoes the fetch-tree
+ render-tree flow. No manual/incremental DOM patching.

- **Add:** a form (title input + submit) does `POST /todos` with
  `{title}`.
- **Complete:** each todo's checkbox `change` event fires
  `PATCH /todos/{id}` with `{done: true/false}`.
- **Delete:** a delete button per todo fires `DELETE /todos/{id}`.
- **Split:** an inline control per todo takes comma-separated (or
  one-per-line) descriptions and fires `POST /todos/{id}/split` with
  `{descriptions: [...]}`.

## Error handling

If any fetch fails (network error or non-2xx response), the error message
is shown in a dedicated `<div id="error">` on the page — no toast library,
no silent failure, no uncaught exception. The div is hidden when there is
no error to show.

## Styling

Pico.css (classless CSS framework) is pulled in via a CDN `<link>` in
`index.html`. It styles plain semantic HTML — nested `<ul>/<li>` for the
tree, `<button>`, `<input>`, `<form>` — with no custom classes required.
`style.css` holds any small custom tweaks on top of it and can start empty.

## Testing

No new automated tests are added for the frontend (no JS test runner is
brought into scope) — verification is manual, by running the app and using
it in a browser. Existing `test_main.py` backend tests are unaffected since
no backend routes or models change.

## Out of scope

- Any backend route/model changes (including a hypothetical
  `GET /todos/tree` endpoint).
- A JS test runner or automated frontend tests.
- Incremental/patched DOM updates (re-fetch-and-rerender only).
- Any framework, build step, or bundler.
