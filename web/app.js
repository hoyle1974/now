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

async function splitTodo(todoId) {
  const raw = window.prompt("Enter split items, one per line:");
  if (raw === null) return;
  const descriptions = raw
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (descriptions.length === 0) return;
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

function renderNode(todo, todosById) {
  const li = document.createElement("li");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = todo.done;
  checkbox.addEventListener("change", () => reportedFailure(toggleDone(todo.todo_id, checkbox.checked)));

  const label = document.createElement("span");
  label.textContent = " " + todo.title + " ";

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => reportedFailure(deleteTodo(todo.todo_id)));

  const splitBtn = document.createElement("button");
  splitBtn.type = "button";
  splitBtn.textContent = "Split";
  splitBtn.addEventListener("click", () => reportedFailure(splitTodo(todo.todo_id)));

  li.append(checkbox, label, deleteBtn, splitBtn);

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
