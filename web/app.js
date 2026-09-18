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

function reportedFailure(promise) {
  return promise.catch(() => {});
}

async function toggleDone(todoId, done) {
  try {
    await apiFetch(`${API_BASE}/${todoId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ done }),
    });
  } finally {
    await loadAndRender();
  }
}

async function deleteTodo(todoId) {
  try {
    await apiFetch(`${API_BASE}/${todoId}`, { method: "DELETE" });
  } finally {
    await loadAndRender();
  }
}

async function saveEdit(todoId, title, dueDate) {
  setActivePanel(null);
  try {
    const body = { title };
    if (dueDate) {
      body.due_date = dueDate;
    }
    await apiFetch(`${API_BASE}/${todoId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } finally {
    await loadAndRender();
  }
}

async function saveSplit(todoId, descriptions) {
  setActivePanel(null);
  try {
    await apiFetch(`${API_BASE}/${todoId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ descriptions }),
    });
  } finally {
    await loadAndRender();
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

let lastRoots = [];
let lastTodosById = new Map();

// Tracks which parent todos are collapsed (children hidden). Absence means
// expanded, so newly split/loaded parents default to expanded.
const collapsedIds = new Set();

// At most one per-row panel (the "more actions" menu, or one of its inline
// editors) is open at a time, so it's a single { todoId, mode } slot rather
// than a separate boolean/id per mode — opening one always means closing
// whatever else was open. mode is "menu" | "edit" | "add" | "split".
let activePanel = null;

function setActivePanel(mode, todoId) {
  activePanel = mode ? { mode, todoId } : null;
}

function isActivePanel(mode, todoId) {
  return activePanel !== null && activePanel.mode === mode && activePanel.todoId === todoId;
}

function formatDate(isoString) {
  return new Date(isoString).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// Strictly overdue (due date has already passed) — used for the red
// due-date badge treatment, which should stay off for something due later
// today.
function isOverdue(todo) {
  if (todo.done || !todo.due_date) return false;
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  return new Date(todo.due_date) < startOfToday;
}

// Overdue OR due today — used for sorting, since "due today" is also worth
// surfacing to the top even though it isn't red yet.
function isUrgent(todo) {
  if (todo.done || !todo.due_date) return false;
  const endOfToday = new Date();
  endOfToday.setHours(23, 59, 59, 999);
  return new Date(todo.due_date) <= endOfToday;
}

// Surfaces overdue/due-today items first within each sibling group (stable
// otherwise via Array.sort), so opening the tree each day shows what needs
// attention first without flattening or otherwise disturbing the underlying
// parent/child structure.
function sortByUrgency(todos) {
  return [...todos].sort((a, b) => {
    const aUrgent = isUrgent(a);
    const bUrgent = isUrgent(b);
    if (aUrgent !== bUrgent) return aUrgent ? -1 : 1;
    if (aUrgent && bUrgent) return new Date(a.due_date) - new Date(b.due_date);
    return 0;
  });
}

// Descendant counts for every node, computed once per render in one
// memoized bottom-up pass rather than re-walking each parent's subtree
// independently (which would revisit shared descendants once per ancestor).
function computeDescendantCounts(todosById) {
  const counts = new Map();
  function countFor(todoId) {
    if (counts.has(todoId)) {
      return counts.get(todoId);
    }
    const todo = todosById.get(todoId);
    let count = 0;
    for (const childId of todo.child_ids) {
      count += 1 + countFor(childId);
    }
    counts.set(todoId, count);
    return count;
  }
  for (const todoId of todosById.keys()) {
    countFor(todoId);
  }
  return counts;
}

function menuItem(label, onClick, extraClass = "") {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `todo-menu-item ${extraClass}`.trim();
  btn.textContent = label;
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return btn;
}

function renderNode(todo, todosById, descendantCounts, depth = 0) {
  const li = document.createElement("li");
  li.className = "todo-node";
  li.style.setProperty("--depth", depth);
  const hasChildren = todo.child_ids.length > 0;
  const isCollapsed = hasChildren && collapsedIds.has(todo.todo_id);

  const row = document.createElement("div");
  row.className = "todo-row";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "todo-toggle";
  if (hasChildren) {
    toggle.textContent = isCollapsed ? "▶" : "▼";
    toggle.setAttribute("aria-label", isCollapsed ? "Expand subtasks" : "Collapse subtasks");
    toggle.addEventListener("click", () => {
      if (collapsedIds.has(todo.todo_id)) {
        collapsedIds.delete(todo.todo_id);
      } else {
        collapsedIds.add(todo.todo_id);
      }
      renderTree();
    });
  } else {
    toggle.classList.add("todo-toggle--spacer");
    toggle.disabled = true;
    toggle.tabIndex = -1;
  }

  const checkboxHit = document.createElement("label");
  checkboxHit.className = "todo-check-hit";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = todo.done;
  checkbox.addEventListener("change", () => reportedFailure(toggleDone(todo.todo_id, checkbox.checked)));
  checkboxHit.appendChild(checkbox);

  const label = document.createElement("span");
  label.className = "todo-title";
  if (todo.done) {
    label.classList.add("todo-title--done");
  }
  label.textContent = todo.title;

  let badge = null;
  if (hasChildren) {
    badge = document.createElement("span");
    badge.className = "todo-count-badge";
    const count = descendantCounts.get(todo.todo_id);
    badge.textContent = `${count} subtask${count === 1 ? "" : "s"}`;
  }

  const meta = document.createElement("span");
  meta.className = "todo-meta";
  // Parent rows already carry a subtask-count badge; repeating "Created ..."
  // on every parent in a deep tree is a lot of low-value text for little
  // payoff, so it's reserved for leaf rows where it's the only metadata.
  // Due date is always shown when set — that one's actionable.
  if (!hasChildren) {
    const created = document.createElement("span");
    created.textContent = `Created ${formatDate(todo.create_date)}`;
    meta.appendChild(created);
  }
  if (todo.due_date) {
    const dueBadge = document.createElement("span");
    dueBadge.className = "todo-due-badge";
    if (isOverdue(todo)) {
      dueBadge.classList.add("todo-due-badge--overdue");
    }
    dueBadge.textContent = `Due ${formatDate(todo.due_date)}`;
    meta.appendChild(dueBadge);
  }

  // Groups with the kebab below so the two share one line when wrapped.
  const metaRow = document.createElement("span");
  metaRow.className = "todo-meta-row";

  const menuWrap = document.createElement("span");
  menuWrap.className = "todo-menu";

  const kebabBtn = document.createElement("button");
  kebabBtn.type = "button";
  kebabBtn.className = "todo-kebab";
  kebabBtn.textContent = "⋮";
  kebabBtn.setAttribute("aria-label", "More actions");
  kebabBtn.setAttribute("aria-haspopup", "true");
  const menuOpen = isActivePanel("menu", todo.todo_id);
  kebabBtn.setAttribute("aria-expanded", String(menuOpen));
  kebabBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    setActivePanel(menuOpen ? null : "menu", todo.todo_id);
    renderTree();
  });
  menuWrap.appendChild(kebabBtn);

  if (menuOpen) {
    const menu = document.createElement("div");
    menu.className = "todo-menu-dropdown";
    menu.setAttribute("role", "menu");

    menu.append(
      menuItem("Add child", () => {
        setActivePanel("add", todo.todo_id);
        renderTree();
      }),
      menuItem("Edit", () => {
        setActivePanel("edit", todo.todo_id);
        renderTree();
      }),
      menuItem("Split", () => {
        setActivePanel("split", todo.todo_id);
        renderTree();
      }),
      menuItem(
        "Delete",
        () => {
          setActivePanel(null);
          reportedFailure(deleteTodo(todo.todo_id));
        },
        "todo-menu-item--danger"
      )
    );
    menuWrap.appendChild(menu);
  }

  metaRow.append(meta, menuWrap);

  row.append(toggle, checkboxHit, label);
  if (badge) {
    row.appendChild(badge);
  }
  row.appendChild(metaRow);
  li.appendChild(row);

  if (isActivePanel("split", todo.todo_id)) {
    li.appendChild(renderSplitEditor(todo));
  }

  if (isActivePanel("add", todo.todo_id)) {
    li.appendChild(renderAddChildEditor(todo));
  }

  if (isActivePanel("edit", todo.todo_id)) {
    li.appendChild(renderEditEditor(todo));
  }

  if (hasChildren && !isCollapsed) {
    const childList = document.createElement("ul");
    const children = sortByUrgency(todo.child_ids.map((id) => todosById.get(id)));
    for (const child of children) {
      childList.appendChild(renderNode(child, todosById, descendantCounts, depth + 1));
    }
    li.appendChild(childList);
  }

  return li;
}

// Shared Save/Cancel row for the inline editors below — each editor supplies
// its own content elements and save behavior, but the button chrome and the
// "Cancel closes this panel" behavior are identical across all of them.
function renderEditorActions(onSave) {
  const buttons = document.createElement("div");
  buttons.className = "split-editor-buttons";

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "todo-btn";
  saveBtn.textContent = "Save";
  saveBtn.addEventListener("click", onSave);

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "outline secondary todo-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => {
    setActivePanel(null);
    renderTree();
  });

  buttons.append(saveBtn, cancelBtn);
  return buttons;
}

function renderSplitEditor(todo) {
  const editor = document.createElement("div");
  editor.className = "split-editor";

  const textarea = document.createElement("textarea");
  textarea.placeholder = "One item per line";
  textarea.rows = 3;

  const buttons = renderEditorActions(() => {
    const descriptions = textarea.value
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    if (descriptions.length === 0) return;
    reportedFailure(saveSplit(todo.todo_id, descriptions));
  });

  editor.append(textarea, buttons);
  return editor;
}

function renderAddChildEditor(todo) {
  const editor = document.createElement("div");
  editor.className = "split-editor";

  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "New subtask title";

  const submit = () => {
    const title = input.value.trim();
    if (!title) return;
    reportedFailure(saveSplit(todo.todo_id, [title]));
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  });

  const buttons = renderEditorActions(submit);

  editor.append(input, buttons);
  return editor;
}

function renderEditEditor(todo) {
  const editor = document.createElement("div");
  editor.className = "split-editor";

  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.placeholder = "Title";
  titleInput.value = todo.title;

  const dueDateLabel = document.createElement("label");
  dueDateLabel.className = "edit-editor-due-label";
  dueDateLabel.textContent = "Due date";
  const dueDateInput = document.createElement("input");
  dueDateInput.type = "date";
  if (todo.due_date) {
    dueDateInput.value = todo.due_date.slice(0, 10);
  }
  dueDateLabel.appendChild(dueDateInput);

  const buttons = renderEditorActions(() => {
    const title = titleInput.value.trim();
    if (!title) return;
    reportedFailure(saveEdit(todo.todo_id, title, dueDateInput.value));
  });

  editor.append(titleInput, dueDateLabel, buttons);
  return editor;
}

function renderTree() {
  const treeEl = document.getElementById("todo-tree");
  treeEl.innerHTML = "";
  if (lastRoots.length === 0) {
    const empty = document.createElement("p");
    empty.className = "todo-empty";
    empty.textContent = "No todos yet — add one above.";
    treeEl.appendChild(empty);
    return;
  }
  const descendantCounts = computeDescendantCounts(lastTodosById);
  for (const root of sortByUrgency(lastRoots)) {
    treeEl.appendChild(renderNode(root, lastTodosById, descendantCounts));
  }
}

async function loadAndRender() {
  const { roots, todosById } = await fetchTree();
  lastRoots = roots;
  lastTodosById = todosById;
  renderTree();
}

document.addEventListener("DOMContentLoaded", () => {
  reportedFailure(loadAndRender());
});

// Clicking anywhere closes an open kebab menu, but not an open editor
// (split/add/edit) — those only close via their own Cancel/Save.
document.addEventListener("click", () => {
  if (activePanel?.mode === "menu") {
    setActivePanel(null);
    renderTree();
  }
});

// On mobile, the on-screen keyboard can cover the input right after it's
// focused, before the viewport has resized — nudge it into view once that
// settles rather than leaving the user typing blind.
document.getElementById("add-title").addEventListener("focus", () => {
  setTimeout(() => {
    document.getElementById("add-title").scrollIntoView({ block: "center", behavior: "smooth" });
  }, 300);
});

document.getElementById("add-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("add-title");
  const title = input.value.trim();
  if (!title) return;
  reportedFailure(
    (async () => {
      await apiFetch(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      input.value = "";
      await loadAndRender();
    })()
  );
});
