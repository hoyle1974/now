const API_BASE = "/todos";

async function apiFetch(path, options = {}) {
  const errorDiv = document.getElementById("error");
  try {
    const response = await fetch(path, options);
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`);
    }
    // Only clear if there's no active undo message
    if (!lastDeleted) {
      errorDiv.hidden = true;
      errorDiv.textContent = "";
    }
    if (response.status === 204) {
      return null;
    }
    return await response.json();
  } catch (err) {
    errorDiv.hidden = false;
    errorDiv.textContent = "Something went wrong — " + err.message;
    clearTimeout(apiFetch.hideTimer);
    apiFetch.hideTimer = setTimeout(() => {
      errorDiv.hidden = true;
    }, 5000);
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
    showUndo(todoId);
  } finally {
    await loadAndRender();
  }
}

// Soft-delete undo: restore a deleted todo within 5 seconds
let lastDeleted = null;
let undoTimer = null;

function showUndo(todoId) {
  lastDeleted = todoId;
  const errorDiv = document.getElementById("error");
  errorDiv.hidden = false;
  errorDiv.textContent = "Deleted · ";
  const undoBtn = document.createElement("button");
  undoBtn.textContent = "Undo";
  undoBtn.style.cssText = "background:none; border:none; color:inherit; text-decoration:underline; cursor:pointer; font:inherit;";
  undoBtn.onclick = async () => {
    clearTimeout(undoTimer);
    try {
      await apiFetch(`${API_BASE}/${todoId}/undelete`, { method: "PATCH" });
      errorDiv.hidden = true;
      await loadAndRender();
    } catch (err) {
      console.error("Undo failed:", err);
    }
  };
  errorDiv.appendChild(undoBtn);

  clearTimeout(undoTimer);
  undoTimer = setTimeout(() => {
    if (lastDeleted === todoId) {
      errorDiv.hidden = true;
      lastDeleted = null;
    }
  }, 5000);
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

async function saveSplit(todoId, descriptions, dueDate = null) {
  setActivePanel(null);
  try {
    const body = { descriptions };
    if (dueDate) {
      body.due_date = dueDate;
    }
    await apiFetch(`${API_BASE}/${todoId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } finally {
    await loadAndRender();
  }
}

async function moveTodo(todoId, direction) {
  try {
    await apiFetch(`${API_BASE}/${todoId}/move/${direction}`, { method: "PATCH" });
  } finally {
    await loadAndRender();
  }
}

// #4: Load the full tree in one request
async function fetchTree() {
  const response = await apiFetch(`${API_BASE}/tree`);
  const todosById = new Map();

  // Convert todosById object to Map
  for (const [id, todo] of Object.entries(response.todosById)) {
    todosById.set(id, todo);
  }

  return { roots: response.roots, todosById };
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

// Inline SVG icons (SF Symbols / Material style strokes) so glyphs render
// crisply and identically on every platform, unlike ▼/⋮ text characters.
const ICONS = {
  chevron: '<path d="M9 5l7 7-7 7"/>',
  more: '<circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  pencil: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
  split: '<path d="M6 4v5a3 3 0 0 0 3 3h9M6 9v6a3 3 0 0 0 3 3h9"/><path d="M15 9l3 3-3 3M15 15l3 3-3 3"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  up: '<path d="M7 14l5-5 5 5"/>',
  down: '<path d="M7 10l5 5 5-5"/>',
};

function icon(name) {
  const span = document.createElement("span");
  span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  return span.firstElementChild;
}

function startOfDay(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

// Whole calendar days from today to the due date (negative = overdue).
function daysUntil(isoString) {
  return Math.round((startOfDay(isoString) - startOfDay(new Date())) / 86400000);
}

// Relative phrasing for the next week, a short date beyond that — the way
// native reminders apps talk about time ("Today", "Tomorrow", "Fri").
function formatDue(isoString) {
  const days = daysUntil(isoString);
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days === -1) return "Yesterday";
  if (days < 0) return `${-days} days overdue`;
  if (days < 7) return new Date(isoString).toLocaleDateString(undefined, { weekday: "long" });
  const sameYear = new Date(isoString).getFullYear() === new Date().getFullYear();
  return new Date(isoString).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

function getTodayString() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function getTomorrowString() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Strictly overdue (due date has already passed) — used for the red
// due-date treatment, which should stay off for something due later today.
function isOverdue(todo) {
  if (todo.done || !todo.due_date) return false;
  return daysUntil(todo.due_date) < 0;
}

// Overdue OR due today — used for sorting, since "due today" is also worth
// surfacing to the top even though it isn't red yet.
function isUrgent(todo) {
  if (todo.done || !todo.due_date) return false;
  return daysUntil(todo.due_date) <= 0;
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

// Descendant { total, done } counts for every node, computed once per render
// in one memoized bottom-up pass rather than re-walking each parent's subtree
// independently (which would revisit shared descendants once per ancestor).
function computeDescendantCounts(todosById) {
  const counts = new Map();
  function countFor(todoId) {
    if (counts.has(todoId)) {
      return counts.get(todoId);
    }
    const todo = todosById.get(todoId);
    const result = { total: 0, done: 0 };
    for (const childId of todo.child_ids) {
      const child = todosById.get(childId);
      const sub = countFor(childId);
      result.total += 1 + sub.total;
      result.done += (child.done ? 1 : 0) + sub.done;
    }
    counts.set(todoId, result);
    return result;
  }
  for (const todoId of todosById.keys()) {
    countFor(todoId);
  }
  return counts;
}

function menuItem(label, iconName, onClick, extraClass = "") {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `todo-menu-item ${extraClass}`.trim();
  btn.setAttribute("role", "menuitem");
  const text = document.createElement("span");
  text.textContent = label;
  btn.append(text, icon(iconName));
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return btn;
}

function iconButton(className, iconName, ariaLabel) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `icon-btn ${className}`;
  btn.setAttribute("aria-label", ariaLabel);
  btn.appendChild(icon(iconName));
  return btn;
}

function renderMeta(todo, hasChildren, counts) {
  const meta = document.createElement("div");
  meta.className = "todo-meta";

  if (hasChildren) {
    const progress = document.createElement("span");
    progress.className = "todo-chip";
    const ring = document.createElement("span");
    ring.className = "todo-progress";
    ring.style.setProperty("--p", counts.total ? counts.done / counts.total : 0);
    const text = document.createElement("span");
    text.textContent = `${counts.done} of ${counts.total}`;
    progress.append(ring, text);
    progress.setAttribute("aria-label", `${counts.done} of ${counts.total} subtasks done`);
    meta.appendChild(progress);
  }

  if (todo.due_date) {
    const due = document.createElement("span");
    due.className = "todo-chip";
    if (isOverdue(todo)) {
      due.classList.add("todo-chip--overdue");
    } else if (isUrgent(todo)) {
      due.classList.add("todo-chip--today");
    }
    const text = document.createElement("span");
    text.textContent = formatDue(todo.due_date);
    due.append(icon("calendar"), text);
    meta.appendChild(due);
  }

  return meta;
}

// #1 & #5: Swipe gestures and title tap-to-rename, plus drag-and-drop reordering
function attachRowInteractions(row, todo) {
  let touchStartX = 0;
  let touchStartY = 0;
  let swiping = false;

  // Drag-and-drop reordering (desktop/tablet)
  row.addEventListener("dragover", (e) => {
    if (todo.parent_id) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";

      const data = e.dataTransfer.getData("application/x-todo-id");
      if (!data) return;

      const { parentId } = JSON.parse(data);
      // Only accept drops from siblings (same parent)
      if (parentId === String(todo.parent_id)) {
        const rect = row.getBoundingClientRect();
        const midY = rect.top + rect.height / 2;

        row.classList.remove("drag-over-before", "drag-over-after");
        if (e.clientY < midY) {
          row.classList.add("drag-over-before");
        } else {
          row.classList.add("drag-over-after");
        }
      }
    }
  });

  row.addEventListener("dragleave", () => {
    row.classList.remove("drag-over-before", "drag-over-after");
  });

  row.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    row.classList.remove("drag-over-before", "drag-over-after");

    const data = e.dataTransfer.getData("application/x-todo-id");
    if (!data) {
      console.error("No drag data");
      return;
    }

    try {
      const parsed = JSON.parse(data);
      const { todoId, parentId } = parsed;

      if (parentId !== String(todo.parent_id)) {
        console.error("Parent mismatch");
        return;
      }
      if (todoId === String(todo.todo_id)) {
        return;
      }

      // Find the dragged todo's order to determine actual direction needed
      const draggedTodo = lastTodosById.get(todoId);
      const targetTodo = todo;

      if (!draggedTodo || !targetTodo) {
        console.error("Could not find todos in map");
        return;
      }

      const draggedOrder = draggedTodo.order_idx ?? 0;
      const targetOrder = targetTodo.order_idx ?? 0;

      console.log(`Drag: from order ${draggedOrder} to ${targetOrder}`);

      // Move multiple times if needed to reach target position
      if (draggedOrder < targetOrder) {
        // Need to move down
        console.log(`Moving down ${targetOrder - draggedOrder} positions`);
        for (let i = draggedOrder; i < targetOrder; i++) {
          try {
            console.log(`  Move ${i + 1}/${targetOrder - draggedOrder}: calling /move/down`);
            const result = await apiFetch(`${API_BASE}/${todoId}/move/down`, { method: "PATCH" });
            console.log(`  Move ${i + 1} result:`, result);
          } catch (err) {
            console.error(`  Move ${i + 1} failed:`, err.message);
            break;
          }
        }
      } else if (draggedOrder > targetOrder) {
        // Need to move up
        console.log(`Moving up ${draggedOrder - targetOrder} positions`);
        for (let i = draggedOrder; i > targetOrder; i--) {
          try {
            console.log(`  Move ${draggedOrder - i + 1}/${draggedOrder - targetOrder}: calling /move/up`);
            const result = await apiFetch(`${API_BASE}/${todoId}/move/up`, { method: "PATCH" });
            console.log(`  Move ${draggedOrder - i + 1} result:`, result);
          } catch (err) {
            console.error(`  Move ${draggedOrder - i + 1} failed:`, err.message);
            break;
          }
        }
      }

      // Reload to show changes
      if (draggedOrder !== targetOrder) {
        console.log("Reloading after moves");
        await loadAndRender();
      }
    } catch (err) {
      console.error("Drop error:", err);
    }
  });

  let longPressTimer = null;

  row.addEventListener("touchstart", (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    swiping = false;

    // Long-press the drag handle to start touch reordering
    if (todo.parent_id && e.target.classList.contains("todo-drag-handle")) {
      longPressTimer = setTimeout(() => {
        row.classList.add("dragging");
        row.style.opacity = "0.6";
      }, 400);
    }
  }, { passive: true });

  row.addEventListener("touchmove", (e) => {
    if (!touchStartX) return;
    const deltaX = e.touches[0].clientX - touchStartX;
    const deltaY = e.touches[0].clientY - touchStartY;

    // If dragging (long-press active), stop swipe detection
    if (row.classList.contains("dragging")) {
      swiping = false;
      return;
    }

    // Only swipe horizontally (not vertical scroll)
    if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 30) {
      swiping = true;
    }
  }, { passive: true });

  row.addEventListener("touchend", (e) => {
    clearTimeout(longPressTimer);

    const isDragging = row.classList.contains("dragging");
    const deltaX = e.changedTouches[0].clientX - touchStartX;
    const deltaY = e.changedTouches[0].clientY - touchStartY;

    // Handle drag reordering (vertical movement while dragging)
    if (isDragging && todo.parent_id && Math.abs(deltaY) > 30) {
      row.classList.remove("dragging");
      row.style.opacity = "1";
      const direction = deltaY > 0 ? "down" : "up";
      reportedFailure(moveTodo(todo.todo_id, direction));
      touchStartX = 0;
      return;
    }

    // Clear drag state
    if (isDragging) {
      row.classList.remove("dragging");
      row.style.opacity = "1";
      touchStartX = 0;
      return;
    }

    if (!swiping || !touchStartX) return;

    // Swipe right: mark done
    if (deltaX > 60) {
      const checkbox = row.querySelector('input[type="checkbox"]');
      if (checkbox && !checkbox.checked) {
        checkbox.checked = true;
        reportedFailure(toggleDone(todo.todo_id, true));
      }
    }
    // Swipe left: delete
    else if (deltaX < -60) {
      setActivePanel(null);
      reportedFailure(deleteTodo(todo.todo_id));
    }

    touchStartX = 0;
  });

  // #5: Tap title to rename
  const titleEl = row.querySelector('.todo-title');
  if (titleEl && !todo.done) {
    titleEl.style.cursor = 'text';
    titleEl.addEventListener('click', (e) => {
      if (e.detail === 2) { // Double-click
        e.stopPropagation();
        const input = document.createElement('input');
        input.type = 'text';
        input.value = todo.title;
        input.style.cssText = 'font-size:inherit; font-weight:inherit; border:1px solid; padding:4px; border-radius:6px;';
        const originalEl = titleEl;

        titleEl.replaceWith(input);
        input.focus();
        input.select();

        const save = async () => {
          const newTitle = input.value.trim();
          if (newTitle && newTitle !== todo.title) {
            await reportedFailure(saveEdit(todo.todo_id, newTitle, todo.due_date ? todo.due_date.slice(0, 10) : ''));
          } else {
            await loadAndRender();
          }
        };

        input.addEventListener('blur', save);
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') save();
          if (e.key === 'Escape') loadAndRender();
        });
      }
    });
  }
}

function renderNode(todo, todosById, descendantCounts, depth = 0) {
  const li = document.createElement("li");
  li.className = "todo-node";
  li.style.setProperty("--depth", depth);
  const hasChildren = todo.child_ids.length > 0;
  const isCollapsed = hasChildren && collapsedIds.has(todo.todo_id);

  const row = document.createElement("div");
  row.className = "todo-row";
  if (todo.done) {
    row.classList.add("is-done");
  }

  // Drag handle for subtasks (non-root todos)
  let dragHandle = null;
  if (todo.parent_id) {
    dragHandle = document.createElement("button");
    dragHandle.type = "button";
    dragHandle.className = "todo-drag-handle";
    dragHandle.textContent = "≡";
    dragHandle.setAttribute("aria-label", "Drag to reorder");
    dragHandle.draggable = true;

    dragHandle.addEventListener("dragstart", (e) => {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("application/x-todo-id", JSON.stringify({
        todoId: String(todo.todo_id),
        parentId: String(todo.parent_id),
      }));
      row.classList.add("dragging");

      // Create visual ghost that follows the cursor
      const dragGhost = row.cloneNode(true);
      dragGhost.id = "drag-ghost-" + Math.random();
      dragGhost.style.cssText = `
        position: fixed;
        pointer-events: none;
        opacity: 0.8;
        z-index: 10000;
        box-shadow: 0 8px 24px rgba(0,0,0,0.2);
        background: var(--card);
        border: 2px solid var(--accent);
        border-radius: 12px;
        width: 300px;
        left: 0;
        top: 0;
      `;
      document.body.appendChild(dragGhost);

      // Update ghost position on drag
      const updateGhost = (moveEvent) => {
        dragGhost.style.left = (moveEvent.clientX - 150) + 'px';
        dragGhost.style.top = (moveEvent.clientY - 30) + 'px';
      };

      document.addEventListener("dragover", updateGhost);

      // Cleanup on dragend
      const cleanup = () => {
        dragGhost.remove();
        document.removeEventListener("dragover", updateGhost);
      };
      dragHandle.addEventListener("dragend", cleanup, { once: true });
    });

    dragHandle.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      document.querySelectorAll(".drag-over-before, .drag-over-after").forEach(el => {
        el.classList.remove("drag-over-before", "drag-over-after");
      });
    });
  }

  const checkboxHit = document.createElement("label");
  checkboxHit.className = "todo-check";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = todo.done;
  checkbox.setAttribute("aria-label", `Mark "${todo.title}" ${todo.done ? "not done" : "done"}`);
  checkbox.addEventListener("change", () => {
    // #3: Instant checkbox response - update UI immediately
    const wasChecked = checkbox.checked;
    if (wasChecked) {
      row.classList.add("is-done");
    } else {
      row.classList.remove("is-done");
    }
    reportedFailure(toggleDone(todo.todo_id, checkbox.checked));
  });
  checkboxHit.appendChild(checkbox);

  const body = document.createElement("div");
  body.className = "todo-body";
  const label = document.createElement("span");
  label.className = "todo-title";
  label.textContent = todo.title;
  body.append(label, renderMeta(todo, hasChildren, descendantCounts.get(todo.todo_id)));

  const trailing = document.createElement("div");
  trailing.className = "todo-trailing";

  if (hasChildren) {
    const toggle = iconButton("todo-toggle", "chevron", isCollapsed ? "Expand subtasks" : "Collapse subtasks");
    toggle.setAttribute("aria-expanded", String(!isCollapsed));
    toggle.addEventListener("click", () => {
      if (collapsedIds.has(todo.todo_id)) {
        collapsedIds.delete(todo.todo_id);
      } else {
        collapsedIds.add(todo.todo_id);
      }
      renderTree();
    });
    trailing.appendChild(toggle);
  }

  const menuWrap = document.createElement("div");
  menuWrap.className = "todo-menu";

  const kebabBtn = iconButton("todo-kebab", "more", "More actions");
  kebabBtn.setAttribute("aria-haspopup", "menu");
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

    const openPanel = (mode) => () => {
      setActivePanel(mode, todo.todo_id);
      renderTree();
    };
    menu.append(
      menuItem("Add subtask", "plus", openPanel("add")),
      menuItem("Edit", "pencil", openPanel("edit")),
      menuItem("Split into subtasks", "split", openPanel("split"))
    );

    // Add move up/down for subtasks (has parent)
    if (todo.parent_id) {
      menu.append(
        menuItem("Move up", "up", () => reportedFailure(moveTodo(todo.todo_id, "up"))),
        menuItem("Move down", "down", () => reportedFailure(moveTodo(todo.todo_id, "down")))
      );
    }

    menu.append(
      menuItem(
        "Delete",
        "trash",
        () => {
          setActivePanel(null);
          reportedFailure(deleteTodo(todo.todo_id));
        },
        "todo-menu-item--danger"
      )
    );
    menuWrap.appendChild(menu);
  }

  trailing.appendChild(menuWrap);

  // Assemble row: drag handle (if subtask), checkbox, body, trailing controls
  if (dragHandle) {
    row.append(dragHandle, checkboxHit, body, trailing);
  } else {
    row.append(checkboxHit, body, trailing);
  }
  li.appendChild(row);

  // Attach swipe/tap interactions
  attachRowInteractions(row, todo);

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
    childList.className = "todo-children";
    // Sort children by order_idx (respecting manual reordering), then by urgency
    const children = todo.child_ids
      .map((id) => todosById.get(id))
      .sort((a, b) => {
        // Primary sort: by order_idx (respects drag-and-drop reordering)
        const aOrder = a.order_idx ?? 999999;
        const bOrder = b.order_idx ?? 999999;
        if (aOrder !== bOrder) return aOrder - bOrder;

        // Secondary sort: by urgency (within same order)
        const aUrgent = isUrgent(a);
        const bUrgent = isUrgent(b);
        if (aUrgent !== bUrgent) return aUrgent ? -1 : 1;
        if (aUrgent && bUrgent) return new Date(a.due_date) - new Date(b.due_date);
        return 0;
      });
    for (const child of children) {
      childList.appendChild(renderNode(child, todosById, descendantCounts, depth + 1));
    }
    li.appendChild(childList);
  }

  return li;
}

// Shared Cancel/Save row for the inline editors below — each editor supplies
// its own content elements and save behavior, but the button chrome and the
// "Cancel closes this panel" behavior are identical across all of them.
function renderEditorActions(onSave, saveLabel = "Save") {
  const buttons = document.createElement("div");
  buttons.className = "sheet-actions";

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "btn btn-plain";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => {
    setActivePanel(null);
    renderTree();
  });

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "btn btn-primary";
  saveBtn.textContent = saveLabel;
  saveBtn.addEventListener("click", onSave);

  buttons.append(cancelBtn, saveBtn);
  return buttons;
}

function renderSheet(...children) {
  const editor = document.createElement("div");
  editor.className = "sheet";
  editor.append(...children);
  // Focus the first field once it's in the DOM, so opening an editor from
  // the menu goes straight to typing instead of needing a second tap.
  requestAnimationFrame(() => editor.querySelector("input, textarea")?.focus());
  return editor;
}

function sheetLabel(text, forEl) {
  const label = document.createElement("label");
  label.className = "sheet-label";
  label.textContent = text;
  forEl.id = `field-${Math.random().toString(36).slice(2)}`;
  label.htmlFor = forEl.id;
  return label;
}

function renderSplitEditor(todo) {
  const textarea = document.createElement("textarea");
  textarea.placeholder = "One subtask per line";
  textarea.rows = 3;

  const buttons = renderEditorActions(() => {
    const descriptions = textarea.value
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    if (descriptions.length === 0) return;
    reportedFailure(saveSplit(todo.todo_id, descriptions));
  }, "Split");

  return renderSheet(sheetLabel("Split into subtasks", textarea), textarea, buttons);
}

function renderAddChildEditor(todo) {
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Subtask title";
  input.enterKeyHint = "done";

  const dueDateInput = document.createElement("input");
  dueDateInput.type = "date";

  const submit = () => {
    const title = input.value.trim();
    if (!title) return;
    reportedFailure(saveSplit(todo.todo_id, [title], dueDateInput.value));
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  });

  return renderSheet(
    sheetLabel("New subtask", input),
    input,
    sheetLabel("Due date (optional)", dueDateInput),
    dueDateInput,
    renderEditorActions(submit, "Add")
  );
}

// #6: Due date shortcuts in edit panel
function renderEditEditor(todo) {
  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.placeholder = "Title";
  titleInput.value = todo.title;

  const dueDateInput = document.createElement("input");
  dueDateInput.type = "date";
  if (todo.due_date) {
    dueDateInput.value = todo.due_date.slice(0, 10);
  }

  const shortcutsDiv = document.createElement("div");
  shortcutsDiv.style.cssText = "display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;";

  const shortcuts = [
    { label: "Today", value: getTodayString() },
    { label: "Tomorrow", value: getTomorrowString() },
    { label: "Clear", value: "" }
  ];

  for (const shortcut of shortcuts) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-plain";
    btn.textContent = shortcut.label;
    btn.style.cssText = "padding:6px 12px; font-size:14px;";
    btn.addEventListener("click", () => {
      dueDateInput.value = shortcut.value;
    });
    shortcutsDiv.appendChild(btn);
  }

  const buttons = renderEditorActions(() => {
    const title = titleInput.value.trim();
    if (!title) return;
    reportedFailure(saveEdit(todo.todo_id, title, dueDateInput.value));
  });

  return renderSheet(
    sheetLabel("Title", titleInput),
    titleInput,
    sheetLabel("Due date", dueDateInput),
    dueDateInput,
    shortcutsDiv,
    buttons
  );
}

function renderEmptyState() {
  const empty = document.createElement("li");
  empty.className = "todo-empty";
  const badge = document.createElement("div");
  badge.className = "todo-empty-icon";
  badge.appendChild(icon("check"));
  const title = document.createElement("p");
  title.className = "todo-empty-title";
  title.textContent = "All clear";
  const text = document.createElement("p");
  text.className = "todo-empty-text";
  text.textContent = "Add your first todo below.";
  empty.append(badge, title, text);
  return empty;
}

// "5 open · 2 overdue" under the large title — the at-a-glance status line.
function renderSummary() {
  const summary = document.getElementById("summary");
  summary.innerHTML = "";
  const all = [...lastTodosById.values()];
  if (all.length === 0) return;
  const open = all.filter((t) => !t.done).length;
  const overdue = all.filter(isOverdue).length;
  summary.append(open === 0 ? "Everything's done" : `${open} open`);
  if (overdue > 0) {
    const span = document.createElement("span");
    span.className = "is-overdue";
    span.textContent = `${overdue} overdue`;
    summary.append(" · ", span);
  }
}

function renderTree() {
  const treeEl = document.getElementById("todo-tree");
  treeEl.innerHTML = "";
  renderSummary();
  if (lastRoots.length === 0) {
    treeEl.appendChild(renderEmptyState());
    return;
  }
  const descendantCounts = computeDescendantCounts(lastTodosById);
  for (const root of sortByUrgency(lastRoots)) {
    treeEl.appendChild(renderNode(root, lastTodosById, descendantCounts));
  }
}

async function loadAndRender() {
  console.log("loadAndRender: fetching tree...");
  const { roots, todosById } = await fetchTree();
  console.log(`loadAndRender: got ${roots.length} roots, ${todosById.size} todos`);
  lastRoots = roots;
  lastTodosById = todosById;
  console.log("loadAndRender: calling renderTree()");
  renderTree();
  console.log("loadAndRender: done");
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("today-label").textContent = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
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

document.getElementById("add-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("add-title");
  const dueInput = document.getElementById("add-due");
  const title = input.value.trim();
  if (!title) return;
  reportedFailure(
    (async () => {
      const body = { title };
      if (dueInput.value) {
        body.due_date = dueInput.value;
      }
      await apiFetch(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      input.value = "";
      dueInput.value = "";
      await loadAndRender();
    })()
  );
});
