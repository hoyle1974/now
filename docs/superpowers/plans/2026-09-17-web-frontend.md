# Web Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight, JS-driven web frontend that lets you view and manage the todo tree (add, complete, delete, split) in a browser, on top of the existing JSON API.

**Architecture:** Static files in `web/` (index.html, app.js, style.css) are served by FastAPI's `StaticFiles` mount at `/`. `app.js` talks to the existing `/todos` JSON API via `fetch()`; no server-side rendering, no build step, no framework. Every mutation re-fetches and re-renders the whole tree.

**Tech Stack:** FastAPI `StaticFiles`, vanilla JavaScript (`fetch`, DOM APIs), Pico.css (classless CSS framework via CDN).

**Spec:** `docs/superpowers/specs/2026-09-17-web-frontend-design.md`

## Global Constraints

- No build step, bundler, or frontend framework — plain HTML/CSS/JS files only.
- Frontend and backend share one FastAPI process/origin — no CORS config.
- Tree is fetched client-side via `GET /todos/root` + recursive `GET /todos/{id}` per `child_ids` (N+1 requests) — no new backend "tree" endpoint.
- Every mutation (add/complete/delete/split) is followed by a full re-fetch + re-render via a single `loadAndRender()` function — no incremental DOM patching.
- Fetch errors (network failure or non-2xx) are shown in `<div id="error">`, never silently swallowed or left as an uncaught exception.
- No new automated frontend tests — verification is manual, in a browser. Backend changes (the static mount) get an automated test since they touch `app/main.py`.

---

## File Structure

```
web/
  index.html   — page shell: error div, add-form, todo tree container, Pico.css + app.js links
  app.js       — all fetch/render/event logic
  style.css    — empty for now, placeholder for future custom tweaks
app/main.py    — modify: mount web/ via StaticFiles at "/", after all /todos routes
```

---

### Task 1: Serve the static frontend shell

**Files:**
- Create: `web/index.html`
- Create: `web/style.css`
- Modify: `app/main.py` (add `StaticFiles` mount at end of file, after all `/todos` routes)
- Test: `test_main.py` (add one test function)

**Interfaces:**
- Produces: a working `/` route serving `web/index.html`, and static file serving for anything else placed in `web/` (e.g. `/app.js`, `/style.css` in later tasks).

- [ ] **Step 1: Write the failing test**

Add to `test_main.py` (uses the existing `client` and `db_setup` fixture already in the file):

```python
def test_root_serves_frontend_shell(db_setup):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Todos</title>" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_main.py::test_root_serves_frontend_shell -v`
Expected: FAIL (404, since no route/mount exists yet at `/`)

- [ ] **Step 3: Create `web/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Todos</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main class="container">
    <h1>Todos</h1>
    <div id="error" hidden></div>

    <form id="add-form">
      <input type="text" id="add-title" name="title" placeholder="New todo" required>
      <button type="submit">Add</button>
    </form>

    <ul id="todo-tree"></ul>
  </main>

  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create empty `web/style.css`**

```css
/* custom tweaks go here */
```

- [ ] **Step 5: Mount the static directory in `app/main.py`**

Add this import near the top, with the other imports:

```python
from fastapi.staticfiles import StaticFiles
```

Add this line at the very end of `app/main.py` (after `split_todo` and all other route definitions — a mount at `/` must come last or it will shadow the `/todos` routes):

```python
app.mount("/", StaticFiles(directory="web", html=True), name="web")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest test_main.py::test_root_serves_frontend_shell -v`
Expected: PASS

- [ ] **Step 7: Run the full test suite to confirm no regressions**

Run: `pytest test_main.py -v`
Expected: all tests PASS (the new static mount is added after every `/todos` route, so it must not shadow any of them)

- [ ] **Step 8: Commit**

```bash
git add web/index.html web/style.css app/main.py test_main.py
git commit -m "feat: serve static frontend shell via StaticFiles mount"
```

---

### Task 2: Fetch and render the todo tree

**Files:**
- Create: `web/app.js`
- Modify: `web/index.html` — none needed (script tag already added in Task 1)

**Interfaces:**
- Consumes: `GET /todos/root` → `list[Todo]`, `GET /todos/{id}` → `Todo`, where `Todo` has at least `todo_id: string`, `title: string`, `done: boolean`, `child_ids: string[]` (per `app/models.py`).
- Produces: `apiFetch(path, options) -> Promise<any|null>` (throws on failure, shows error in `#error`), `fetchTree() -> Promise<{roots: Todo[], todosById: Map<string, Todo>}>`, `renderNode(todo, todosById) -> HTMLLIElement`, `loadAndRender() -> Promise<void>`. Later tasks call `loadAndRender()` after every mutation and rely on these exact names.

- [ ] **Step 1: Create `web/app.js` with the core data + render logic**

```javascript
const API_BASE = "/todos";

async function apiFetch(path, options = {}) {
  const errorDiv = document.getElementById("error");
  try {
    const response = await fetch(path, options);
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`);
    }
    errorDiv.hidden = true;
    errorDiv.textContent = "";
    if (response.status === 204) {
      return null;
    }
    return await response.json();
  } catch (err) {
    errorDiv.hidden = false;
    errorDiv.textContent = err.message;
    throw err;
  }
}

async function fetchTree() {
  const roots = await apiFetch(`${API_BASE}/root`);
  const todosById = new Map();

  async function fetchAndStore(todo) {
    todosById.set(todo.todo_id, todo);
    for (const childId of todo.child_ids) {
      const child = await apiFetch(`${API_BASE}/${childId}`);
      await fetchAndStore(child);
    }
  }

  for (const root of roots) {
    await fetchAndStore(root);
  }

  return { roots, todosById };
}

function renderNode(todo, todosById) {
  const li = document.createElement("li");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = todo.done;

  const label = document.createElement("span");
  label.textContent = " " + todo.title + " ";

  li.append(checkbox, label);

  if (todo.child_ids.length > 0) {
    const childList = document.createElement("ul");
    for (const childId of todo.child_ids) {
      const child = todosById.get(childId);
      childList.appendChild(renderNode(child, todosById));
    }
    li.appendChild(childList);
  }

  return li;
}

async function loadAndRender() {
  const { roots, todosById } = await fetchTree();
  const treeEl = document.getElementById("todo-tree");
  treeEl.innerHTML = "";
  for (const root of roots) {
    treeEl.appendChild(renderNode(root, todosById));
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadAndRender();
});
```

- [ ] **Step 2: Seed test data and verify manually in a browser**

Run: `uvicorn app.main:app --reload`

In another terminal, seed a parent and a child todo:

```bash
curl -s -X POST http://127.0.0.1:8000/todos -H "Content-Type: application/json" -d '{"title": "Groceries"}'
```

Copy the `todo_id` from the response, then split it into children:

```bash
curl -s -X POST http://127.0.0.1:8000/todos/<todo_id>/split -H "Content-Type: application/json" -d '{"descriptions": ["Milk", "Eggs"]}'
```

Open `http://127.0.0.1:8000/` in a browser and verify:
- "Groceries" appears as a top-level list item with an unchecked checkbox.
- "Milk" and "Eggs" appear nested under it in a sub-list.
- No error message is visible.

- [ ] **Step 3: Commit**

```bash
git add web/app.js
git commit -m "feat: fetch and render todo tree in the frontend"
```

---

### Task 3: Add-todo form

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- Consumes: `apiFetch`, `loadAndRender` from Task 2; `POST /todos` with `{title: string}` → `Todo`.
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Add the form submit handler to `web/app.js`**

Append to the end of `web/app.js`:

```javascript
document.getElementById("add-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("add-title");
  const title = input.value.trim();
  if (!title) return;
  await apiFetch(API_BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  input.value = "";
  await loadAndRender();
});
```

- [ ] **Step 2: Verify manually in a browser**

With `uvicorn app.main:app --reload` running, open `http://127.0.0.1:8000/`, type a title into the "New todo" field, and click "Add". Verify:
- The new todo appears as a top-level list item without a page reload.
- The input field is cleared after submit.

- [ ] **Step 3: Commit**

```bash
git add web/app.js
git commit -m "feat: wire up add-todo form"
```

---

### Task 4: Complete/uncomplete toggle

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- Consumes: `apiFetch`, `loadAndRender`; `PATCH /todos/{id}` with `{done: boolean}` → `Todo`.
- Produces: `toggleDone(todoId, done) -> Promise<void>`, wired into each rendered checkbox.

- [ ] **Step 1: Add `toggleDone` and wire it into `renderNode`'s checkbox**

In `web/app.js`, change the checkbox creation inside `renderNode` from:

```javascript
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = todo.done;
```

to:

```javascript
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = todo.done;
  checkbox.addEventListener("change", () => toggleDone(todo.todo_id, checkbox.checked));
```

Then append this function anywhere at the top level of `web/app.js` (e.g. right after `apiFetch`):

```javascript
async function toggleDone(todoId, done) {
  await apiFetch(`${API_BASE}/${todoId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ done }),
  });
  await loadAndRender();
}
```

- [ ] **Step 2: Verify manually in a browser**

With the server running, open `http://127.0.0.1:8000/` and click a todo's checkbox. Verify:
- The checkbox stays checked after the re-render.
- Reloading the page (full refresh) keeps it checked — confirms the `PATCH` persisted, not just local DOM state.

- [ ] **Step 3: Commit**

```bash
git add web/app.js
git commit -m "feat: wire up complete/uncomplete checkbox"
```

---

### Task 5: Delete a todo

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- Consumes: `apiFetch`, `loadAndRender`; `DELETE /todos/{id}` → `204 No Content`.
- Produces: `deleteTodo(todoId) -> Promise<void>`, wired into a delete button per rendered node.

- [ ] **Step 1: Add a delete button to `renderNode` and the `deleteTodo` function**

In `web/app.js`, inside `renderNode`, change:

```javascript
  li.append(checkbox, label);
```

to:

```javascript
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => deleteTodo(todo.todo_id));

  li.append(checkbox, label, deleteBtn);
```

Then append this function at the top level of `web/app.js`:

```javascript
async function deleteTodo(todoId) {
  await apiFetch(`${API_BASE}/${todoId}`, { method: "DELETE" });
  await loadAndRender();
}
```

- [ ] **Step 2: Verify manually in a browser**

With the server running, open `http://127.0.0.1:8000/`, click "Delete" on a todo that has children. Verify:
- The todo and all its rendered children disappear from the tree (the backend's `ON DELETE CASCADE` foreign key removes child rows too — confirm via `curl http://127.0.0.1:8000/todos/root` that they're actually gone, not just hidden).

- [ ] **Step 3: Commit**

```bash
git add web/app.js
git commit -m "feat: wire up delete button"
```

---

### Task 6: Split a todo into children

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- Consumes: `apiFetch`, `loadAndRender`; `POST /todos/{id}/split` with `{descriptions: string[]}` → `Todo`.
- Produces: `splitTodo(todoId) -> Promise<void>`, wired into a split button per rendered node.

- [ ] **Step 1: Add a split button to `renderNode` and the `splitTodo` function**

In `web/app.js`, inside `renderNode`, change:

```javascript
  li.append(checkbox, label, deleteBtn);
```

to:

```javascript
  const splitBtn = document.createElement("button");
  splitBtn.type = "button";
  splitBtn.textContent = "Split";
  splitBtn.addEventListener("click", () => splitTodo(todo.todo_id));

  li.append(checkbox, label, deleteBtn, splitBtn);
```

Then append this function at the top level of `web/app.js`:

```javascript
async function splitTodo(todoId) {
  const raw = window.prompt("Enter split items, one per line:");
  if (raw === null) return;
  const descriptions = raw
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (descriptions.length === 0) return;
  await apiFetch(`${API_BASE}/${todoId}/split`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ descriptions }),
  });
  await loadAndRender();
}
```

- [ ] **Step 2: Verify manually in a browser**

With the server running, open `http://127.0.0.1:8000/`, click "Split" on a todo, enter two lines of text in the prompt (e.g. `Task A` / `Task B`), and confirm. Verify:
- Both new items appear nested under the original todo.
- Clicking "Split" and then Cancel on the prompt makes no change (no empty children added).

- [ ] **Step 3: Commit**

```bash
git add web/app.js
git commit -m "feat: wire up split-into-children control"
```

---

## Self-Review Notes

- **Spec coverage:** static mount (Task 1), N+1 client-side tree fetch (Task 2), add/complete/delete/split interactions (Tasks 3-6), error div (Task 2's `apiFetch`), Pico.css + empty `style.css` (Task 1) — all spec sections have a task.
- **Placeholder scan:** no TBDs; every step has literal code or literal shell commands.
- **Type/name consistency:** `apiFetch`, `fetchTree`, `renderNode`, `loadAndRender`, `toggleDone`, `deleteTodo`, `splitTodo` are used with the same names and signatures everywhere they're referenced across tasks.
