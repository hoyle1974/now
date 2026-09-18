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
let lastRoots = [];
let lastTodosById = new Map();

function formatDate(isoString) {
  return new Date(isoString).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function renderNode(todo, todosById) {
  const li = document.createElement("li");
  li.className = "todo-node";

  const row = document.createElement("div");
  row.className = "todo-row";

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = todo.done;
  checkbox.addEventListener("change", () => reportedFailure(toggleDone(todo.todo_id, checkbox.checked)));

  const label = document.createElement("span");
  label.className = "todo-title";
  if (todo.done) {
    label.classList.add("todo-title--done");
  }
  label.textContent = todo.title;

  const meta = document.createElement("span");
  meta.className = "todo-meta";
  const metaParts = [`Created ${formatDate(todo.create_date)}`];
  if (todo.due_date) {
    metaParts.push(`Due ${formatDate(todo.due_date)}`);
  }
  meta.textContent = metaParts.join(" · ");

  const actions = document.createElement("span");
  actions.className = "todo-actions";

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "outline secondary todo-btn";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => reportedFailure(deleteTodo(todo.todo_id)));

  const splitBtn = document.createElement("button");
  splitBtn.type = "button";
  splitBtn.className = "outline secondary todo-btn";
  splitBtn.textContent = "Split";
  splitBtn.addEventListener("click", () => {
    splittingTodoId = todo.todo_id;
    renderTree();
  });

  actions.append(splitBtn, deleteBtn);
  row.append(checkbox, label, meta, actions);
  li.appendChild(row);

  if (splittingTodoId === todo.todo_id) {
    li.appendChild(renderSplitEditor(todo));
  }

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
