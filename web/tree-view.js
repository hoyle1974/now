// Summary line, renderTree, loadAndRender, and the page lifecycle (focus, online, DOMContentLoaded).
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).
// "5 open · 2 overdue" under the large title — the at-a-glance status line.
// The app-icon badge shows how many open todos are due today or overdue.
let lastBadge = null;
function updateBadge(all) {
  const count = Badge.dueCount(all, (t) => daysUntil(t.due_date));
  if (count === lastBadge) return;
  lastBadge = count;
  Badge.apply(navigator, count);
}

// iOS only allows the badge once notification permission is granted, and that
// prompt needs a tap, so offer it as a small link until it's answered.
function syncBadgeButton() {
  document.getElementById("badge-enable").hidden =
    !Badge.canPrompt(navigator, typeof Notification === "undefined" ? undefined : Notification);
}

function renderSummary() {
  const summary = document.getElementById("summary");
  summary.innerHTML = "";
  const all = [...model.todosById.values()];
  updateBadge(all);
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
  const doneCount = doneToday();
  if (doneCount > 0) {
    const span = document.createElement("span");
    span.className = "is-done-today";
    span.textContent = `${doneCount} done today \u2728`;
    summary.append(" · ", span);
  }
}

// Every re-render (a sync ack, a subtask fold, a refresh) rebuilds the open
// edit/split/add sheet from the todo, which would throw away what was typed.
// Carry the field values and focus across, matched by position in the sheet.
function sheetFields(treeEl) {
  return [...treeEl.querySelectorAll(".sheet input, .sheet textarea, .sheet select")];
}

function snapshotSheet(treeEl) {
  if (!activePanel || !["edit", "add", "split"].includes(activePanel.mode)) return null;
  const fields = sheetFields(treeEl);
  if (!fields.length) return null;
  return {
    key: `${activePanel.mode}:${activePanel.todoId}`,
    values: fields.map((f) => (f.type === "checkbox" ? f.checked : f.value)),
    focus: fields.indexOf(document.activeElement),
    caret: document.activeElement && document.activeElement.selectionStart,
  };
}

function restoreSheet(treeEl, snap) {
  if (!snap || !activePanel || snap.key !== `${activePanel.mode}:${activePanel.todoId}`) return;
  const fields = sheetFields(treeEl);
  if (fields.length !== snap.values.length) return;
  fields.forEach((f, i) => {
    const v = snap.values[i];
    if (f.type === "checkbox") f.checked = v;
    else if (f.value !== v) f.value = v;
    f.dispatchEvent(new Event("input")); // keeps dependent controls (time, repeat) in step
  });
  // renderSheet focuses the first field on the next frame; land after it.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const f = snap.focus >= 0 ? fields[snap.focus] : null;
    if (!f || !f.isConnected) return;
    f.focus();
    if (snap.caret != null && f.setSelectionRange) {
      try { f.setSelectionRange(snap.caret, snap.caret); } catch (e) { /* date/time/number */ }
    }
  }));
}

function renderTree() {
  const treeEl = document.getElementById("todo-tree");
  const sheetSnap = snapshotSheet(treeEl);
  treeEl.innerHTML = "";
  renderSummary();
  if (model.roots.length === 0) {
    treeEl.appendChild(renderEmptyState());
    if (activePanel && activePanel.mode === "view") setActivePanel(null);
    return;
  }
  const descendantCounts = computeDescendantCounts(model.todosById);
  // Manual order wins, as it does for subtasks. Same ordering the sync
  // engine's move op counts steps against.
  const roots = sinkDone([...model.roots].sort((a, b) => (a.order_idx ?? 999999) - (b.order_idx ?? 999999)));
  for (const root of roots) {
    treeEl.appendChild(renderNode(root, model.todosById, descendantCounts));
  }
  // The viewer's todo was deleted remotely or its ancestor collapsed: nothing
  // rendered it, so don't leave a dead panel (and a scroll lock) behind.
  if (activePanel && activePanel.mode === "view" && !treeEl.querySelector(".sheet-full")) {
    setActivePanel(null);
  }
  restoreSheet(treeEl, sheetSnap);
  placeOpenMenu();
}

// Closes the viewer, or steps back from an edit sheet opened from it.
// Returns whether it did anything.
function stepBack() {
  if (!activePanel) return false;
  if (activePanel.mode === "view") {
    setActivePanel(null);
    renderTree();
    return true;
  }
  if (activePanel.mode === "edit" && viewerOrigin) {
    const id = viewerOrigin;
    setActivePanel("view", id);
    renderTree();
    return true;
  }
  return false;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") stepBack();
});

// The menu opens below its kebab. Near the bottom of the screen that puts it
// under the composer (or an Undo toast), so open it upward if there's room above, otherwise
// scroll it into view.
function placeOpenMenu() {
  document.body.classList.remove("menu-room");
  const menu = document.querySelector(".todo-menu-dropdown");
  if (!menu) return;
  const composer = document.getElementById("add-form");
  const composerTop = composer.getClientRects().length
    ? composer.getBoundingClientRect().top
    : window.innerHeight;
  // A visible toast (e.g. Undo after a delete) floats above the composer and covers the menu too.
  const toast = document.getElementById("error");
  const toastTop = toast && !toast.hidden ? toast.getBoundingClientRect().top : composerTop;
  const bottomLimit = Math.min(composerTop, toastTop) - 8;
  const topLimit = document.querySelector(".tabs-wrap").getBoundingClientRect().bottom + 8;
  const kebab = menu.parentElement.querySelector(".todo-kebab").getBoundingClientRect();
  // offsetHeight, because the open animation scales the menu's own rect.
  const height = menu.offsetHeight;
  if (kebab.bottom + 4 + height <= bottomLimit) return;
  if (kebab.top - 4 - height >= topLimit) {
    menu.classList.add("todo-menu-dropdown--up");
  } else {
    // A short page can't scroll far enough to clear the composer, so add room.
    document.body.classList.add("menu-room");
    window.scrollBy({ top: kebab.bottom + 4 + height - bottomLimit, behavior: "auto" });
  }
}

// Replace the local model with the server's tree; unsent edits in the outbox
// are re-applied on top so they stay visible. If an edit was queued or
// finished while the fetch was in flight, the snapshot may predate it, so wait
// for the outbox to settle and read again instead of painting stale state.
async function loadAndRender() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const epoch = engine.epoch();
    const startedAt = performance.now();
    let tree;
    try {
      tree = await fetchTree();
    } catch (e) {
      logEvent("tree-fail", e.message);
      throw e;
    }
    logEvent("tree", `fetched rev ${tree.rev}, ${tree.todosById.size} todos (${Math.round(performance.now() - startedAt)}ms)`);
    if (engine.epoch() === epoch) {
      engine.rebuild(tree);
      // The ranking is computed from the same data, so keep it in step.
      if (activeTab === "next") reportedFailure(refreshNext());
      return;
    }
    logEvent("tree", "an edit landed during the fetch; discarding and fetching again");
    await engine.flush();
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("today-label").textContent = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  renderSyncStatus(engine.status());
  // Ask the browser not to evict the outbox under storage pressure.
  try { navigator.storage?.persist?.(); } catch (e) { /* best effort */ }
  await engine.load();
  await reportedFailure(loadAndRender());
  // Offline launch with edits waiting: the list stays empty and the outbox is
  // held (sync.js needsTree) until a tree loads, so say so and keep trying.
  if (engine.needsTree()) {
    showNotice({ level: "error", message: `Offline — couldn't load your list. Your ${engine.pending()} unsent edit(s) are saved and will sync once it loads.` });
    document.getElementById("error").dataset.kind = "offline";
    const timer = setInterval(() => (engine.needsTree() ? retryFirstLoad() : clearInterval(timer)), 15000);
  }
  engine.kick();
});

// Retry the first tree load (see above); a no-op once one has loaded, and only
// one attempt runs at a time (the timer, a return to the app and a pill tap can coincide).
let firstLoadRetry = null;
function retryFirstLoad() {
  if (firstLoadRetry || !engine.needsTree()) return;
  firstLoadRetry = reportedFailure(loadAndRender()).then(() => {
    firstLoadRetry = null;
    const errorDiv = document.getElementById("error");
    if (!engine.needsTree() && errorDiv.dataset.kind === "offline") errorDiv.hidden = true;
  });
}

// Coming back to the app: resend anything pending and see if another window
// wrote while we were away. visibilitychange/pageshow are the reliable signals
// on phones; focus covers switching between desktop windows. How long we were
// away decides whether the 30s debounce applies: a real absence always checks.
let leftAt = null;
function markAway() {
  if (leftAt === null) leftAt = Date.now();
}
function onReturn(force = false) {
  const awayMs = leftAt === null ? 0 : Date.now() - leftAt;
  leftAt = null;
  retryFirstLoad();
  engine.kick();
  freshness.check({ awayMs, force });
}
window.addEventListener("blur", () => { logEvent("blur"); markAway(); });
window.addEventListener("focus", () => { logEvent("focus"); onReturn(); });
window.addEventListener("online", () => { logEvent("online"); onReturn(true); }); // connectivity is back: always look
window.addEventListener("offline", () => logEvent("offline"));
window.addEventListener("pageshow", (e) => {
  logEvent("pageshow", e.persisted ? "restored from the back-forward cache" : "normal");
  if (e.persisted) onReturn();
});
window.addEventListener("pagehide", (e) => logEvent("pagehide", e.persisted ? "going into the back-forward cache" : "unloading"));
// Page Lifecycle events (Chromium): logged so we can see if the OS froze the page.
document.addEventListener("freeze", () => logEvent("freeze"));
document.addEventListener("resume", () => logEvent("resume"));
document.addEventListener("visibilitychange", () => {
  logEvent("visibility", document.visibilityState);
  if (document.visibilityState === "visible") onReturn();
  else markAway();
});
// Leaving the rename box (or any inline field) can unblock a deferred refresh.
document.getElementById("todo-tree").addEventListener("focusout", () => {
  setTimeout(() => freshness.poke(), 0);
});

// Tapping the status pill drains the outbox, then pulls the latest from the
// server (the way to pick up changes made on another device).
document.getElementById("sync-status").addEventListener("click", async () => {
  retryFirstLoad();
  engine.kick(true); // navigator.onLine can be wrong; let a manual tap try anyway
  await engine.flush();
  if (engine.pending() === 0) {
    await reportedFailure(loadAndRender());
  }
});

// Clicking anywhere closes an open kebab menu, but not an open editor
// (split/add/edit) — those only close via their own Cancel/Save.
document.addEventListener("click", () => {
  if (activePanel?.mode === "menu") {
    setActivePanel(null);
    renderTree();
  }
});
