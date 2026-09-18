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
  editingTodoId = null;
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
  splittingTodoId = null;
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

// Tracks which todo (if any) currently has its inline split editor open.
// Entering/leaving this state re-renders from the already-fetched tree
// data below rather than re-fetching, so it's instant and doesn't disturb
// unrelated in-flight edits.
let splittingTodoId = null;
// Same idea, for the single-child quick-add row (a lighter-weight
// alternative to Split for adding just one child under a specific parent).
let addingChildToTodoId = null;
let lastRoots = [];
let lastTodosById = new Map();

// Tracks which parent todos are collapsed (children hidden). Absence means
// expanded, so newly split/loaded parents default to expanded.
const collapsedIds = new Set();

// Tracks which todo (if any) has its per-row "more actions" menu open.
// Always tap-to-open rather than hover-revealed, since this app runs
// primarily on touch devices where hover doesn't exist.
let openMenuTodoId = null;

// Tracks which todo (if any) has its title/due-date editor open.
let editingTodoId = null;

function formatDate(isoString) {
  return new Date(isoString).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function countDescendants(todo, todosById) {
  let count = 0;
  for (const childId of todo.child_ids) {
    count += 1 + countDescendants(todosById.get(childId), todosById);
  }
  return count;
}

function renderNode(todo, todosById, depth = 0) {
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
    const count = countDescendants(todo, todosById);
    badge.textContent = `${count} subtask${count === 1 ? "" : "s"}`;
  }

  const meta = document.createElement("span");
  meta.className = "todo-meta";
  // Parent rows already carry a subtask-count badge; repeating "Created ..."
  // on every parent in a deep tree is a lot of low-value text for little
  // payoff, so it's reserved for leaf rows where it's the only metadata.
  // Due date is always shown when set — that one's actionable.
  const metaParts = hasChildren ? [] : [`Created ${formatDate(todo.create_date)}`];
  if (todo.due_date) {
    metaParts.push(`Due ${formatDate(todo.due_date)}`);
  }
  meta.textContent = metaParts.join(" · ");

  const menuWrap = document.createElement("span");
  menuWrap.className = "todo-menu";

  const kebabBtn = document.createElement("button");
  kebabBtn.type = "button";
  kebabBtn.className = "todo-kebab";
  kebabBtn.textContent = "⋮";
  kebabBtn.setAttribute("aria-label", "More actions");
  kebabBtn.setAttribute("aria-haspopup", "true");
  const menuOpen = openMenuTodoId === todo.todo_id;
  kebabBtn.setAttribute("aria-expanded", String(menuOpen));
  kebabBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    openMenuTodoId = menuOpen ? null : todo.todo_id;
    renderTree();
  });
  menuWrap.appendChild(kebabBtn);

  if (menuOpen) {
    const menu = document.createElement("div");
    menu.className = "todo-menu-dropdown";
    menu.setAttribute("role", "menu");

    const addChildItem = document.createElement("button");
    addChildItem.type = "button";
    addChildItem.className = "todo-menu-item";
    addChildItem.textContent = "Add child";
    addChildItem.addEventListener("click", (event) => {
      event.stopPropagation();
      openMenuTodoId = null;
      splittingTodoId = null;
      editingTodoId = null;
      addingChildToTodoId = todo.todo_id;
      renderTree();
    });

    const editItem = document.createElement("button");
    editItem.type = "button";
    editItem.className = "todo-menu-item";
    editItem.textContent = "Edit";
    editItem.addEventListener("click", (event) => {
      event.stopPropagation();
      openMenuTodoId = null;
      addingChildToTodoId = null;
      splittingTodoId = null;
      editingTodoId = todo.todo_id;
      renderTree();
    });

    const splitItem = document.createElement("button");
    splitItem.type = "button";
    splitItem.className = "todo-menu-item";
    splitItem.textContent = "Split";
    splitItem.addEventListener("click", (event) => {
      event.stopPropagation();
      openMenuTodoId = null;
      addingChildToTodoId = null;
      editingTodoId = null;
      splittingTodoId = todo.todo_id;
      renderTree();
    });

    const deleteItem = document.createElement("button");
    deleteItem.type = "button";
    deleteItem.className = "todo-menu-item todo-menu-item--danger";
    deleteItem.textContent = "Delete";
    deleteItem.addEventListener("click", (event) => {
      event.stopPropagation();
      openMenuTodoId = null;
      reportedFailure(deleteTodo(todo.todo_id));
    });

    menu.append(addChildItem, editItem, splitItem, deleteItem);
    menuWrap.appendChild(menu);
  }

  row.append(toggle, checkboxHit, label);
  if (badge) {
    row.appendChild(badge);
  }
  row.append(meta, menuWrap);
  li.appendChild(row);

  if (splittingTodoId === todo.todo_id) {
    li.appendChild(renderSplitEditor(todo));
  }

  if (addingChildToTodoId === todo.todo_id) {
    li.appendChild(renderAddChildEditor(todo));
  }

  if (editingTodoId === todo.todo_id) {
    li.appendChild(renderEditEditor(todo));
  }

  if (hasChildren && !isCollapsed) {
    const childList = document.createElement("ul");
    for (const childId of todo.child_ids) {
      const child = todosById.get(childId);
      childList.appendChild(renderNode(child, todosById, depth + 1));
    }
    li.appendChild(childList);
  }

  return li;
}

function renderSplitEditor(todo) {
  const editor = document.createElement("div");
  editor.className = "split-editor";

  const textarea = document.createElement("textarea");
  textarea.placeholder = "One item per line";
  textarea.rows = 3;

  const buttons = document.createElement("div");
  buttons.className = "split-editor-buttons";

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "todo-btn";
  saveBtn.textContent = "Save";
  saveBtn.addEventListener("click", () => {
    const descriptions = textarea.value
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    if (descriptions.length === 0) return;
    reportedFailure(saveSplit(todo.todo_id, descriptions));
  });

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "outline secondary todo-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => {
    splittingTodoId = null;
    renderTree();
  });

  buttons.append(saveBtn, cancelBtn);
  editor.append(textarea, buttons);
  return editor;
}

function renderAddChildEditor(todo) {
  const editor = document.createElement("div");
  editor.className = "split-editor";

  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "New subtask title";

  const buttons = document.createElement("div");
  buttons.className = "split-editor-buttons";

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "todo-btn";
  addBtn.textContent = "Add";
  const submit = () => {
    const title = input.value.trim();
    if (!title) return;
    addingChildToTodoId = null;
    reportedFailure(saveSplit(todo.todo_id, [title]));
  };
  addBtn.addEventListener("click", submit);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  });

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "outline secondary todo-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => {
    addingChildToTodoId = null;
    renderTree();
  });

  buttons.append(addBtn, cancelBtn);
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

  const buttons = document.createElement("div");
  buttons.className = "split-editor-buttons";

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "todo-btn";
  saveBtn.textContent = "Save";
  saveBtn.addEventListener("click", () => {
    const title = titleInput.value.trim();
    if (!title) return;
    reportedFailure(saveEdit(todo.todo_id, title, dueDateInput.value));
  });

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "outline secondary todo-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => {
    editingTodoId = null;
    renderTree();
  });

  buttons.append(saveBtn, cancelBtn);
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
  for (const root of lastRoots) {
    treeEl.appendChild(renderNode(root, lastTodosById));
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

document.addEventListener("click", () => {
  if (openMenuTodoId !== null) {
    openMenuTodoId = null;
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
