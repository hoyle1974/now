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

async function toggleDone(todoId, done) {
  await apiFetch(`${API_BASE}/${todoId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ done }),
  });
  await loadAndRender();
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
  checkbox.addEventListener("change", () => toggleDone(todo.todo_id, checkbox.checked));

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
