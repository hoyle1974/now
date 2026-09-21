// The list / Next up tabs and the Next up rows.
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).

// ---- Tabs: the list, and "Next up" --------------------------------------------

let activeTab = "list";
const scrollByTab = { list: 0, next: 0 };
const treeEl = document.getElementById("todo-tree");
const nextView = document.getElementById("next-view");

function setTab(tab) {
  if (tab === activeTab) return;
  scrollByTab[activeTab] = window.scrollY;
  activeTab = tab;
  document.body.dataset.tab = tab;
  for (const btn of document.querySelectorAll(".segmented-btn")) {
    btn.setAttribute("aria-selected", String(btn.dataset.tab === tab));
  }
  treeEl.hidden = tab !== "list";
  nextView.hidden = tab !== "next";
  if (window.Trash) Trash.onTab(tab); // web/trash.js
  if (tab === "next") {
    renderNext();
    reportedFailure(refreshNext());
  }
  window.scrollTo(0, scrollByTab[tab] || 0);
}

for (const btn of document.querySelectorAll(".segmented-btn")) {
  btn.addEventListener("click", () => setTab(btn.dataset.tab));
}

// The server ranks the todos (app/next_up.py); this only draws its answer.
let nextItems = null;
let nextStale = false;
let nextRequest = 0;

async function refreshNext() {
  const mine = ++nextRequest;
  // Unsent edits aren't on the server yet, so let them land before asking.
  await Promise.race([engine.flush(), new Promise((resolve) => setTimeout(resolve, 4000))]);
  try {
    const response = await fetch(`${API_BASE}/next?today=${getTodayString()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status}`);
    const data = await response.json();
    if (mine !== nextRequest) return; // a newer request is in flight
    nextItems = data.items;
    nextStale = false;
  } catch (err) {
    logEvent("next-fail", err.message);
    if (mine !== nextRequest) return;
    nextStale = true;
  }
  renderNext();
}

function renderNextRow(item) {
  const li = document.createElement("li");
  const row = document.createElement("button");
  row.type = "button";
  row.className = "next-row";
  const color = Fields.effectiveColor(model.todosById.get(item.todo_id) || {}, model.todosById);
  if (color) row.dataset.color = color;

  const rank = document.createElement("span");
  rank.className = "next-rank";
  rank.textContent = item.rank;

  const body = document.createElement("span");
  body.className = "next-body";
  const title = document.createElement("span");
  title.className = "next-title";
  title.textContent = item.title;
  body.appendChild(title);

  const meta = document.createElement("span");
  meta.className = "next-meta";
  if (item.path.length) {
    const path = document.createElement("span");
    path.className = "next-path";
    path.textContent = item.path.join(" › ");
    meta.appendChild(path);
  }
  if (item.effective_due) {
    const days = daysUntil(item.effective_due);
    const due = document.createElement("span");
    due.className = "todo-chip" + (Due.isOverdue(item.effective_due) ? " todo-chip--overdue" : days === 0 ? " todo-chip--today" : "");
    const text = document.createElement("span");
    text.textContent = formatDue(item.effective_due) + (item.due_source === "parent" ? " · from parent" : "");
    due.append(icon("calendar"), text);
    meta.appendChild(due);
  }
  if (meta.childNodes.length) body.appendChild(meta);
  if (item.blocked_by && item.blocked_by.length) {
    const blocked = document.createElement("span");
    blocked.className = "next-blocked";
    row.classList.add("next-row--blocked");
    const more = item.blocked_by.length - 1;
    blocked.textContent = `Blocked by ${item.blocked_by[0]}` + (more ? ` +${more}` : "");
    body.appendChild(blocked);
  }

  const chevron = icon("chevron");
  chevron.classList.add("next-chevron");
  row.append(rank, body, chevron);
  row.addEventListener("click", (event) => {
    // A keyboard "click" has no position; use the row's own.
    const box = row.getBoundingClientRect();
    focusTodo(item.todo_id, event.detail === 0 ? box.top : event.clientY);
  });
  li.appendChild(row);
  return li;
}

function renderNext() {
  const list = document.getElementById("next-list");
  const note = document.getElementById("next-note");
  list.innerHTML = "";
  note.hidden = !nextStale;
  note.textContent = "Couldn't reach the server, so this may be out of date.";
  if (nextItems === null) {
    const loading = document.createElement("li");
    loading.className = "next-empty";
    loading.textContent = "Loading…";
    list.appendChild(loading);
    return;
  }
  if (nextItems.length === 0) {
    list.appendChild(renderEmptyState("Nothing to do", "You're all caught up."));
    return;
  }
  for (const item of nextItems) list.appendChild(renderNextRow(item));
}

// Jump from "Next up" to the list with this todo pulled into view: the row is
// scrolled to where the finger just was, so it stays under it, ready to check
// off or open the menu.
function focusTodo(todoId, tapY) {
  const todo = model.todosById.get(todoId);
  if (!todo) {
    reportedFailure(refreshNext());
    return;
  }
  // Open every collapsed ancestor so the row exists.
  for (let p = todo.parent_id && model.todosById.get(String(todo.parent_id)); p;
       p = p.parent_id && model.todosById.get(String(p.parent_id))) {
    setCollapsed(p.todo_id, false);
  }
  setActivePanel(null);
  spotlight(todoId);
  setTab("list");
  renderTree();

  const row = treeEl.querySelector(`[data-todo-id="${CSS.escape(todoId)}"] > .todo-row`);
  if (!row) return;
  const top = document.querySelector(".tabs-wrap").getBoundingClientRect().bottom + 8;
  const composerTop = addForm.getClientRects().length
    ? addForm.getBoundingClientRect().top
    : window.innerHeight;
  // Keep the row where the finger was, but never under the sticky tabs or composer.
  const y = Math.min(Math.max(tapY, top), composerTop - row.offsetHeight - 12);
  window.scrollTo(0, row.getBoundingClientRect().top + window.scrollY - y);
}
