// Open-panel state and history, icons, date helpers, outline copy, row menu and meta.
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).
// At most one per-row panel (the "more actions" menu, or one of its inline
// editors) is open at a time, so it's a single { todoId, mode } slot rather
// than a separate boolean/id per mode — opening one always means closing
// whatever else was open. mode is "menu" | "edit" | "add" | "split" | "view".
let activePanel = null;

// The todo whose edit sheet was opened from the viewer, so Cancel/Save/Escape
// go back to it instead of the list.
let viewerOrigin = null;

// Back gesture / browser back closes the full-screen viewer or edit sheet. One
// history entry covers "a full-screen panel is open": it is pushed on entering
// and popped (history.back) when a button closes the panel, so nothing goes
// stale. Every failure is swallowed: without history support the panel simply
// has no back gesture, as before.
let historyPushed = false;
let ignorePops = 0;
function syncHistory(open) {
  try {
    if (open && !historyPushed) {
      history.pushState({ nowPanel: 1 }, "");
      historyPushed = true;
    } else if (!open && historyPushed) {
      historyPushed = false;
      ignorePops += 1;
      history.back();
    }
  } catch (e) { /* no history support: skip */ }
}

window.addEventListener("popstate", () => {
  if (ignorePops > 0) { ignorePops -= 1; return; }
  if (!historyPushed) return;
  historyPushed = false; // the browser already consumed our entry
  if (!stepBack() && activePanel && activePanel.mode === "edit") {
    setActivePanel(null); // an edit sheet opened from the list: same as Cancel
    renderTree();
  }
});

function setActivePanel(mode, todoId) {
  activePanel = mode ? { mode, todoId } : null;
  if (mode !== "edit") viewerOrigin = null;
  // The full-screen viewer/edit sheet is fixed; keep the page behind it still.
  document.body.style.overflow = mode === "view" || mode === "edit" ? "hidden" : "";
  syncHistory(mode === "view" || mode === "edit");
  // After the caller has re-rendered: the closed editor's inputs are gone by then.
  if (!mode) setTimeout(() => freshness.poke(), 0);
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
  repeat: '<path d="M4 11V9a3 3 0 0 1 3-3h11M15 3l3 3-3 3M20 13v2a3 3 0 0 1-3 3H6M9 21l-3-3 3-3"/>',
  pencil: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
  split: '<path d="M6 4v5a3 3 0 0 0 3 3h9M6 9v6a3 3 0 0 0 3 3h9"/><path d="M15 9l3 3-3 3M15 15l3 3-3 3"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="currentColor" stroke="none"/><circle cx="4.5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="4.5" cy="18" r="1" fill="currentColor" stroke="none"/>',
  folder: '<path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h3.2l2 2.5H18a2.5 2.5 0 0 1 2.5 2.5v6.5A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5z"/>',
  grip: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  up: '<path d="M7 14l5-5 5 5"/>',
  down: '<path d="M7 10l5 5 5-5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/>',
};

function icon(name) {
  const span = document.createElement("span");
  span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  return span.firstElementChild;
}

// Strictly overdue (due date has already passed) — used for the red
// due-date treatment, which should stay off for something due later today.
function isOverdue(todo) {
  if (todo.done || !todo.due_date || !Types.hasField(todo, "due_date")) return false;
  return Due.isOverdue(todo.due_date);
}

// Overdue OR due today — used for sorting, since "due today" is also worth
// surfacing to the top even though it isn't red yet.
function isUrgent(todo) {
  if (todo.done || !todo.due_date || !Types.hasField(todo, "due_date")) return false;
  return Due.daysUntil(todo.due_date) <= 0;
}

// Descendant { total, done } counts for every node, computed once per render
// in one memoized bottom-up pass rather than re-walking each parent's subtree
// independently (which would revisit shared descendants once per ancestor).
function computeDescendantCounts(todosById) {
  return Types.descendantCounts(todosById);
}

async function copyOutline(todoId) {
  const text = Outline.toOutline(model.todosById, todoId);
  try {
    await navigator.clipboard.writeText(text);
    showNotice({ level: "info", message: "Copied to clipboard" });
  } catch (e) {
    showNotice({ level: "error", message: "Couldn't copy: " + e.message });
  }
}

function menuItem(label, iconName, onClick, extraClass = "") {
  const btn = DOM.button("", `todo-menu-item ${extraClass}`.trim());
  btn.setAttribute("role", "menuitem");
  btn.append(DOM.el("span", null, label), icon(iconName));
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return btn;
}

function iconButton(className, iconName, ariaLabel) {
  const btn = DOM.button("", `icon-btn ${className}`);
  btn.setAttribute("aria-label", ariaLabel);
  btn.appendChild(icon(iconName));
  return btn;
}

function renderMeta(todo, hasChildren, counts) {
  const meta = document.createElement("div");
  meta.className = "todo-meta";

  if (hasChildren && counts.total && Types.can(todo, "showsProgress")) {
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

  if (todo.repeat && Types.hasField(todo, "repeat")) {
    const rep = document.createElement("span");
    rep.className = "todo-chip";
    const label = document.createElement("span");
    label.textContent = Due.formatRepeat(todo.repeat);
    rep.append(icon("repeat"), label);
    meta.appendChild(rep);
  }

  if (todo.due_date && Types.hasField(todo, "due_date")) {
    const due = document.createElement("span");
    due.className = "todo-chip";
    if (isOverdue(todo)) {
      due.classList.add("todo-chip--overdue");
    } else if (isUrgent(todo)) {
      due.classList.add("todo-chip--today");
    }
    const text = document.createElement("span");
    text.textContent = Due.format(todo.due_date);
    due.append(icon("calendar"), text);
    meta.appendChild(due);
  }

  const blockedChip = FieldsUI.blockedChip(todo);
  if (blockedChip) meta.appendChild(blockedChip);

  return meta;
}

