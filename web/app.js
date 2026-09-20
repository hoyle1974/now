const API_BASE = "/todos";
const APP_VERSION = "54";

// On-device diagnostics (see the "log" link under the title). Kept in
// localStorage so it survives the phone killing the page while locked.
let logStorage = null;
try {
  logStorage = window.localStorage;
} catch (e) {
  // Storage blocked: the log still works for this page load.
}
const eventLog = EventLog.create({ storage: logStorage });
const logEvent = (kind, detail) => eventLog.log(kind, detail);

function nextPageNumber() {
  try {
    const n = Number(logStorage.getItem("todo-page-count") || 0) + 1;
    logStorage.setItem("todo-page-count", String(n));
    return n;
  } catch (e) {
    return "?";
  }
}

function isStandalone() {
  return window.navigator.standalone === true ||
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
}

logEvent("load", `page #${nextPageNumber()} v${APP_VERSION} ${document.visibilityState} ` +
  `online=${navigator.onLine} standalone=${isStandalone()}`);

// True while the toast shows an apiFetch failure (the only thing apiFetch may clear).
let apiErrorShown = false;

// Every writer of the shared #error toast starts here: it stops the other
// writers' timers and handlers so none can clobber (or later clear) the new one.
function claimToast(errorDiv) {
  clearTimeout(apiFetch.hideTimer);
  clearTimeout(noticeTimer);
  clearTimeout(undoTimer);
  apiErrorShown = false;
  lastDeleted = null;
  errorDiv.onclick = null;
  delete errorDiv.dataset.kind;
}

async function apiFetch(path, options = {}) {
  const errorDiv = document.getElementById("error");
  try {
    const response = await fetch(path, options);
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`);
    }
    // Only clear a failure apiFetch itself showed; never a sync-engine notice
    // or the Undo toast.
    if (apiErrorShown) {
      apiErrorShown = false;
      clearTimeout(apiFetch.hideTimer);
      errorDiv.hidden = true;
      errorDiv.textContent = "";
    }
    if (response.status === 204) {
      return null;
    }
    return await response.json();
  } catch (err) {
    logEvent("fetch-fail", `${path}: ${err.message}`);
    claimToast(errorDiv);
    errorDiv.hidden = false;
    errorDiv.textContent = "Something went wrong — " + err.message;
    apiErrorShown = true;
    apiFetch.hideTimer = setTimeout(() => {
      if (apiErrorShown) { apiErrorShown = false; errorDiv.hidden = true; }
    }, 5000);
    throw err;
  }
}

function reportedFailure(promise) {
  return promise.catch(() => {});
}

// ---- Sync engine ---------------------------------------------------------
// Actions no longer wait for the server: they apply to the local model and go
// into a persisted outbox that web/sync.js drains in the background.

async function sendRequest(req) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(req.path, {
      method: req.method,
      headers: req.headers,
      body: req.body === undefined ? undefined : JSON.stringify(req.body),
      signal: controller.signal,
    });
    let body = null;
    if (response.status !== 204 && (response.headers.get("content-type") || "").includes("json")) {
      body = await response.json();
    }
    const header = (name) => {
      const value = response.headers.get(name);
      return value === null ? undefined : Number(value);
    };
    return { status: response.status, body, prev: header("X-Rev-Prev"), rev: header("X-Rev") };
  } finally {
    clearTimeout(timer);
  }
}

let noticeTimer = null;

function showNotice({ level, message }) {
  const errorDiv = document.getElementById("error");
  claimToast(errorDiv);
  errorDiv.hidden = false;
  errorDiv.textContent = message;
  if (level === "error") {
    // Permanent failures stay until dismissed.
    errorDiv.onclick = () => { errorDiv.hidden = true; };
  } else {
    noticeTimer = setTimeout(() => { errorDiv.hidden = true; }, 5000);
  }
}

// What the pill shows combines two things: the outbox (Syncing / Offline /
// Error) and, when the outbox is empty, what the freshness check is doing.
let engineStatus = { state: "synced", pending: 0 };
let phase = "idle";
let phaseSince = 0;
let phaseTimer = null;
const MIN_PHASE_MS = 800; // long enough to actually be read

// Nudge reacts to sync news: a recovery, or a batch of changes finally landing.
let lastSyncState = null;
let syncPeak = 0;
function reactToSync(state, pending) {
  const was = lastSyncState;
  lastSyncState = state;
  if (state === "syncing") syncPeak = Math.max(syncPeak, pending);
  if (!window.Mascot) return;
  if (state === "offline" && was !== "offline") {
    window.Mascot.react("Offline. I'll keep your changes safe.", { key: "offline", cooldown: 300000, happy: false, delay: 1500 });
  } else if (state === "synced" && (was === "offline" || was === "error")) {
    window.Mascot.react("Back online. All synced \u2713", { key: "recovered", cooldown: 20000 });
    syncPeak = 0;
  } else if (state === "synced" && was === "syncing") {
    if (syncPeak >= 3) window.Mascot.react(`${syncPeak} changes synced \u2713`, { key: "batch", cooldown: 120000 });
    syncPeak = 0;
  }
}

function renderSyncStatus(st) {
  if (st) engineStatus = st;
  reactToSync(engineStatus.state, engineStatus.pending);
  const el = document.getElementById("sync-status");
  const { state, pending } = engineStatus;
  let dataState = state;
  let text;
  if (state === "syncing") {
    text = `Syncing ${pending}…` + (engineStatus.unsaved ? " (not saved on device)" : "");
  } else if (state === "offline" && engineStatus.auth) {
    text = `Sign in to sync \u00b7 ${pending} pending`;
  } else if (state === "offline") {
    text = `Offline · ${pending} pending` + (engineStatus.unsaved ? " (not saved on device)" : "");
  } else if (state === "error") {
    text = "Sync error";
  } else if (phase === "checking") {
    dataState = "checking";
    text = "Checking for changes…";
  } else if (phase === "refreshing") {
    dataState = "checking";
    text = "Updating…";
  } else if (phase === "retrying") {
    dataState = "checking";
    text = "Reconnecting…";
  } else if (phase === "waiting") {
    dataState = "waiting";
    text = "Updates waiting";
  } else if (phase === "unreachable") {
    dataState = "offline";
    text = "Couldn't check for updates";
  } else {
    text = "Synced";
  }
  el.dataset.state = dataState;
  el.textContent = text;
}

// Called by the freshness check. A transient phase (checking/updating) that
// would end almost immediately is held for MIN_PHASE_MS so it can be seen.
function setPhase(next) {
  clearTimeout(phaseTimer);
  const held = performance.now() - phaseSince;
  const transient = phase === "checking" || phase === "refreshing" || phase === "retrying";
  if (next === "idle" && transient && held < MIN_PHASE_MS) {
    phaseTimer = setTimeout(() => setPhase("idle"), MIN_PHASE_MS - held);
    return;
  }
  const wasRefreshing = phase === "refreshing";
  phase = next;
  phaseSince = performance.now();
  renderSyncStatus();
  // The list was re-downloaded because another device changed it (not the
  // routine refresh at launch): let the mascot mention it.
  if (wasRefreshing && next === "idle" && performance.now() > 15000 && window.Mascot) {
    window.Mascot.react("Fresh changes from your other device \u2728", { key: "remote", cooldown: 120000 });
  }
}

const model = Sync.createModel();
FieldsUI.init({ model, focusTodo: (id, y) => focusTodo(id, y) });
const engine = Sync.createEngine({
  model,
  store: IdbStore.create(),
  send: sendRequest,
  refetch: () => fetchTree(),
  onChange: () => renderTree(),
  onStatus: (st) => {
    renderSyncStatus(st);
    // The outbox just drained: a refresh that was waiting on it can go ahead.
    if (st.state === "synced") freshness.poke();
  },
  onNotice: showNotice,
  onLog: logEvent,
  isOnline: () => navigator.onLine !== false,
  onRemap: (tmp, real) => {
    // Ids the UI keeps state under change when the server assigns real ones.
    if (activePanel && activePanel.todoId === tmp) activePanel.todoId = real;
    if (lastDeleted === tmp) lastDeleted = real;
  },
});

AttachmentsUI.init({
  model,
  notify: (message) => showNotice({ level: "error", message }),
  observeRev: (prev, rev) => engine.observeRev(prev, rev),
});

// Is the user in the middle of typing into the list (an inline editor, or the
// rename box)? A refresh re-renders the list and would wipe that text. The
// composer at the bottom sits outside the list, so it doesn't count.
function editingInTree() {
  // The open viewer counts too: a refresh would rebuild it (dropping an
  // in-flight upload, the lightbox and the scroll position). Closing it pokes.
  if (activePanel && activePanel.mode !== "menu") return true;
  const el = document.activeElement;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA") && !!el.closest("#todo-tree");
}

// Picks up writes made from another window or device. No timer: it checks
// only when this window regains focus/visibility (see the listeners below), so
// an unfocused or backgrounded window sends nothing.
const freshness = Freshness.create({
  engine,
  fetchRev: async () => {
    const response = await fetch(`${API_BASE}/rev`);
    if (!response.ok) throw new Error(`rev check failed: ${response.status}`);
    return response.json(); // { rev, version }
  },
  appVersion: APP_VERSION,
  reload: () => location.reload(),
  reloadGuard: {
    get: () => { try { return sessionStorage.getItem("reloaded-for-version"); } catch (e) { return null; } },
    set: (v) => { try { sessionStorage.setItem("reloaded-for-version", v); } catch (e) { /* private mode: no guard */ } },
  },
  refresh: () => loadAndRender(),
  editorOpen: editingInTree,
  onPhase: setPhase,
  onLog: logEvent,
  // Retry a failed check only while someone is looking at the page.
  isActive: () => document.visibilityState === "visible",
});

// These stay async so existing `reportedFailure(action(...))` call sites work.
// How many todos were checked off on this device today: a small streak-style
// reward in the header. Local only, since todos carry no completion time.
const DONE_TODAY_KEY = "now.doneToday";
function doneToday(delta = 0) {
  const today = new Date().toDateString();
  let state = { day: today, n: 0 };
  try {
    const saved = JSON.parse(localStorage.getItem(DONE_TODAY_KEY) || "null");
    if (saved && saved.day === today) state = saved;
    if (delta) {
      state.n = Math.max(0, state.n + delta);
      localStorage.setItem(DONE_TODAY_KEY, JSON.stringify(state));
    }
  } catch (_) { /* storage unavailable: no counter */ }
  return state.n;
}

async function toggleDone(todoId, done) {
  const count = doneToday(done ? 1 : -1);
  if (done) reactToDoneCount(count, model.todosById.get(todoId));
  engine.enqueue({ kind: "patch", target_id: todoId, payload: { done } });
  if (!done) return; // one-way: un-doing a subtask never reopens its parent
  // Finishing the last open subtask finishes the parent (and so on upward).
  const completed = [todoId];
  for (const parentId of Autodone.ancestorsToComplete(model, todoId)) {
    celebrate(parentId);
    engine.enqueue({ kind: "patch", target_id: parentId, payload: { done: true } });
    completed.push(parentId);
  }
  // A repeating todo that just got completed spawns its next occurrence.
  for (const id of completed) spawnNextOccurrence(id);
}

// Once per todo: the server ignores a second request and the local model
// remembers one is on its way (spawned_id), so ticking and unticking is safe.
function spawnNextOccurrence(todoId) {
  const todo = model.todosById.get(todoId);
  if (!todo || !todo.repeat || todo.spawned_id) return;
  engine.enqueue({ kind: "repeat", target_id: todoId, payload: { today: getTodayString() } });
}

// Collapse state lives on the todo so it survives refresh and syncs across
// devices. A no-op when already in the requested state, to avoid empty writes.
function setCollapsed(todoId, collapsed) {
  const todo = model.todosById.get(todoId);
  if (!todo || Boolean(todo.collapsed) === collapsed) return;
  engine.enqueue({ kind: "patch", target_id: todoId, payload: { collapsed } });
}

async function deleteTodo(todoId) {
  if (engine.enqueue({ kind: "delete", target_id: todoId })) {
    showUndo(todoId);
  }
}

// Soft-delete undo: restore a deleted todo within 5 seconds
let lastDeleted = null;
let undoTimer = null;

function showUndo(todoId) {
  const errorDiv = document.getElementById("error");
  claimToast(errorDiv);
  lastDeleted = todoId;
  errorDiv.hidden = false;
  errorDiv.textContent = "Deleted · ";
  const undoBtn = document.createElement("button");
  undoBtn.textContent = "Undo";
  undoBtn.className = "toast-action";
  undoBtn.onclick = () => {
    clearTimeout(undoTimer);
    errorDiv.hidden = true;
    lastDeleted = null;
    engine.enqueue({ kind: "undelete", target_id: todoId });
  };
  errorDiv.appendChild(undoBtn);

  undoTimer = setTimeout(() => {
    if (lastDeleted === todoId) {
      errorDiv.hidden = true;
      lastDeleted = null;
    }
  }, 5000);
}

// dueDate undefined = rename only (leave due date/time and repeat alone).
async function saveEdit(todoId, title, dueDate, repeat = null, fields = {}) {
  setActivePanel(viewerOrigin === todoId ? "view" : null, todoId);
  // null explicitly clears the due date (and a repeat rule needs a date).
  // fields: only the changed color/links/blocked_by/references (see fields.js).
  engine.enqueue({ kind: "patch", target_id: todoId,
    payload: Fields.patchPayload({ title, dueDate, repeat, fields }) });
}

async function saveSplit(todoId, descriptions, dueDate = null) {
  setActivePanel(null);
  const payload = { descriptions };
  if (dueDate) {
    payload.due_date = dueDate;
  }
  engine.enqueue({ kind: "split", target_id: todoId, payload });
}

async function moveTodo(todoId, direction) {
  engine.enqueue({ kind: "move", target_id: todoId, payload: { direction } });
}

// #4: Load the full tree in one request
async function fetchTree() {
  const response = await apiFetch(`${API_BASE}/tree`);
  const todosById = new Map();

  // Convert todosById object to Map
  for (const [id, todo] of Object.entries(response.todosById)) {
    todosById.set(id, todo);
  }

  return { roots: response.roots, todosById, rev: response.rev };
}

// One-shot visual states keyed by todo id. Every edit re-renders the whole
// list, which would wipe a CSS animation started on the live element, so the
// renderer re-applies these classes for the length of the animation instead.
const justCompleted = new Map(); // todo id -> timer; also holds the row in place until it sinks
let focusedId = null;
let focusedTimer = null;

function celebrate(todoId) {
  clearTimeout(justCompleted.get(todoId));
  justCompleted.set(todoId, setTimeout(() => {
    justCompleted.delete(todoId);
    // The rows now drop below the open ones. Wait until the last quick tap has
    // settled so the list never reshuffles between two taps, and don't
    // re-render under typed text; it will sink on the next render instead.
    if (!justCompleted.size && !editingInTree()) renderTree();
  }, 1400));
  if (navigator.vibrate) navigator.vibrate(12); // Android only; iOS ignores it
  if (window.Sound) window.Sound.pop();
  // Confetti from the checkbox once the row has rendered; a bigger burst when
  // that was the last open todo.
  requestAnimationFrame(() => {
    const box = document.querySelector(`[data-todo-id="${todoId}"] .todo-check`);
    if (box && window.Sparkle) {
      const r = box.getBoundingClientRect();
      window.Sparkle.burst(r.left + r.width / 2, r.top + r.height / 2);
    }
    if (window.Sparkle && model.todosById.size && [...model.todosById.values()].every((t) => t.done)) {
      window.Sparkle.celebrateAll();
      if (window.Sound) window.Sound.fanfare();
      if (window.Mascot) window.Mascot.cheer();
    }
  });
}

function spotlight(todoId) {
  focusedId = todoId;
  clearTimeout(focusedTimer);
  focusedTimer = setTimeout(() => {
    focusedId = null;
    document.querySelectorAll(".todo-row.is-focused").forEach((el) => el.classList.remove("is-focused"));
  }, 2400);
}

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
  const day = formatDueDay(isoString);
  // A timed due shows its time ("Today 3:00 PM"); "N days overdue" stays terse.
  if (!Due.hasTime(isoString) || daysUntil(isoString) < -1) return day;
  const time = new Date(isoString).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${day} ${time}`;
}

function formatDueDay(isoString) {
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
  return Due.isOverdue(todo.due_date);
}

// Overdue OR due today — used for sorting, since "due today" is also worth
// surfacing to the top even though it isn't red yet.
function isUrgent(todo) {
  if (todo.done || !todo.due_date) return false;
  return daysUntil(todo.due_date) <= 0;
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

  if (todo.repeat) {
    const rep = document.createElement("span");
    rep.className = "todo-chip";
    const label = document.createElement("span");
    label.textContent = Due.formatRepeat(todo.repeat);
    rep.append(icon("repeat"), label);
    meta.appendChild(rep);
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

  const blockedChip = FieldsUI.blockedChip(todo);
  if (blockedChip) meta.appendChild(blockedChip);

  return meta;
}

// The drag in progress, or null: { todoId, li }. Tracked here (not on the
// DOM) because every edit re-renders the whole list.
let dragState = null;
const LONG_PRESS_MS = 350;
const LONG_PRESS_SLOP = 8;

// Where a drop at (x, y) would land: the row under the pointer, or the nearest
// one when the pointer is between rows or beyond the ends, plus which part of
// the row it is on (above it, below it, or in its middle, meaning "nest").
function dropTargetAt(y) {
  const rows = [...document.querySelectorAll("#todo-tree .todo-row")]
    .filter((r) => !dragState.li.contains(r));
  if (!rows.length) return null;
  let best = null;
  let bestDistance = Infinity;
  for (const row of rows) {
    const rect = row.getBoundingClientRect();
    const distance = y < rect.top ? rect.top - y : y > rect.bottom ? y - rect.bottom : 0;
    if (distance < bestDistance) { best = { row, rect }; bestDistance = distance; }
  }
  const { row, rect } = best;
  const zone = bestDistance > 0
    ? (y < rect.top ? "before" : "after")
    : Reorder.zoneFor(rect, y);
  const li = row.closest("li");
  const plan = Reorder.planDrop(model, dragState.todoId, li.dataset.todoId, zone);
  return { row, li, zone, plan };
}

let dropLine = null;
let dropRow = null;

function clearDropHint() {
  if (dropLine) dropLine.hidden = true;
  if (dropRow) dropRow.classList.remove("drop-inside");
  dropRow = null;
}

function showDropHint(target) {
  clearDropHint();
  if (!target || !target.plan) return;
  if (target.zone === "inside") {
    dropRow = target.row;
    dropRow.classList.add("drop-inside");
    return;
  }
  if (!dropLine) {
    dropLine = document.createElement("div");
    dropLine.className = "drop-line";
    document.body.appendChild(dropLine);
  }
  // "Below" a row that has children means below its whole subtree.
  const rect = (target.zone === "before" ? target.row : target.li).getBoundingClientRect();
  const rowRect = target.row.getBoundingClientRect();
  dropLine.style.left = `${rowRect.left + 8}px`;
  dropLine.style.width = `${rowRect.width - 16}px`;
  dropLine.style.top = `${(target.zone === "before" ? rect.top : rect.bottom) - 1.5}px`;
  dropLine.hidden = false;
}

// Applies the drop: one reparent op (optimistic, queued like any edit).
function commitDrop(target) {
  const state = dragState;
  dragState = null;
  clearDropHint();
  if (!state || !target || !target.plan || !engine.enqueue({
    kind: "reparent", target_id: state.todoId, payload: target.plan,
  })) {
    renderTree();
    return;
  }
  // Show what was just dropped into.
  if (target.plan.parent_id) setCollapsed(target.plan.parent_id, false);
}

// #1 & #5: Swipe gestures and title tap-to-rename
function attachRowInteractions(row, todo) {
  let touchStartX = 0;
  let touchStartY = 0;
  let swiping = false;

  row.addEventListener("touchstart", (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    swiping = false;

    if (e.target.closest(".todo-drag-handle")) touchStartX = 0;
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
    if (!touchStartX) return;

    const isDragging = row.classList.contains("dragging");
    const deltaX = e.changedTouches[0].clientX - touchStartX;
    const deltaY = e.changedTouches[0].clientY - touchStartY;

    // Handle drag reordering (vertical movement while dragging)
    if (isDragging && Math.abs(deltaY) > 30) {
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
        celebrate(todo.todo_id);
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

        let finished = false; // Escape/Enter/blur must act once (removing the input fires blur)
        const save = async () => {
          if (finished) return;
          finished = true;
          const newTitle = input.value.trim();
          if (newTitle && newTitle !== todo.title) {
            await reportedFailure(saveEdit(todo.todo_id, newTitle, undefined));
          } else {
            renderTree();
          }
        };

        input.addEventListener('blur', save);
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') save();
          if (e.key === 'Escape') { finished = true; renderTree(); }
        });
      }
    });
  }
}

// Done rows display below the open ones in their group, each part keeping its
// stored order (this never touches order_idx). A row that was just completed
// stays put until its animation ends.
function sinkDone(todos) {
  const sunk = (t) => t.done && !justCompleted.has(t.todo_id);
  return [...todos.filter((t) => !sunk(t)), ...todos.filter(sunk)];
}

function renderNode(todo, todosById, descendantCounts, depth = 0) {
  const li = document.createElement("li");
  li.className = "todo-node";
  li.dataset.todoId = todo.todo_id;
  li.style.setProperty("--depth", depth);
  const hasChildren = todo.child_ids.length > 0;
  const isCollapsed = hasChildren && todo.collapsed;

  // A row shows only its own stored state: a done parent does not make its
  // subtasks look done, and they can still be checked and unchecked.
  const shownDone = todo.done;
  const row = document.createElement("div");
  row.className = "todo-row";
  if (shownDone) {
    row.classList.add("is-done");
  }
  if (justCompleted.has(todo.todo_id) && todo.done) {
    row.classList.add("just-done");
  }
  if (focusedId === todo.todo_id) {
    row.classList.add("is-focused");
  }

  // Long-press a row to drag it: drop above/below another row to move there, or
  // onto the middle of a row to make it a subtask of that row.
  if (model.todosById.size > 1) {
    // Hard press: the drag only starts after a long-press anywhere on the row
    // (so scrolling and taps are untouched). Moving before the threshold is a
    // scroll and cancels; when armed the row lifts (with a small buzz where
    // supported) and the finger can then drag it.
    row.addEventListener("contextmenu", (e) => { if (pressing) e.preventDefault(); });
    let pressing = false;
    // Registered up front (non-passive) so iOS lets us stop the scroll once armed.
    row.addEventListener("touchmove", (t) => { if (dragState && t.cancelable) t.preventDefault(); }, { passive: false });
    row.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || dragState) return;
      if (e.target.closest("input, textarea, label, a, button:not(.todo-drag-handle)")) return;
      const pid = e.pointerId;
      let lastY = e.clientY;
      pressing = true;
      const stop = () => {
        pressing = false;
        press.end();
        row.classList.remove("armed");
        window.removeEventListener("pointermove", onPreMove);
        window.removeEventListener("pointerup", onPreEnd);
        window.removeEventListener("pointercancel", onPreEnd);
      };
      const press = Reorder.longPress(() => {
        if (!row.isConnected) { stop(); return; }
        row.classList.add("armed");
        try { navigator.vibrate && navigator.vibrate(12); } catch (_) { /* optional */ }
        window.removeEventListener("pointermove", onPreMove);
        window.removeEventListener("pointerup", onPreEnd);
        window.removeEventListener("pointercancel", onPreEnd);
        beginDrag(pid, lastY);
      }, { delay: LONG_PRESS_MS, slop: LONG_PRESS_SLOP });
      const onPreMove = (m) => {
        if (m.pointerId !== pid) return;
        lastY = m.clientY;
        press.move(m.clientX, m.clientY);
      };
      const onPreEnd = (u) => { if (u.pointerId === pid) stop(); };
      window.addEventListener("pointermove", onPreMove);
      window.addEventListener("pointerup", onPreEnd);
      window.addEventListener("pointercancel", onPreEnd);
      press.start(e.clientX, e.clientY);
    });

    const beginDrag = (pid, startY) => {
      pressing = false;
      row.classList.remove("armed");
      const rowRect = row.getBoundingClientRect();
      const grabY = startY - rowRect.top;
      dragState = { todoId: String(todo.todo_id), li };
      row.classList.add("dragging");

      const ghost = row.cloneNode(true);
      ghost.classList.remove("dragging");
      ghost.style.cssText = `position:fixed;left:${rowRect.left}px;top:0;width:${rowRect.width}px;
        pointer-events:none;z-index:10000;background:var(--card);border-radius:12px;
        box-shadow:0 8px 24px rgba(0,0,0,0.2);will-change:transform;
        transform:translate3d(0,${rowRect.top}px,0) scale(1.03);`;
      document.body.appendChild(ghost);

      // Track the gesture on window: the row can re-render under the finger.
      let pointerY = startY;
      let target = null;
      let scrollTimer = null;
      const update = () => {
        ghost.style.transform = `translate3d(0,${pointerY - grabY}px,0) scale(1.03)`;
        target = dropTargetAt(pointerY);
        showDropHint(target);
      };
      // Near the top or bottom edge, scroll so far-away rows can be reached.
      const autoScroll = () => {
        const edge = 90;
        const speed = pointerY < edge ? -(edge - pointerY) / 6
          : pointerY > window.innerHeight - edge ? (pointerY - (window.innerHeight - edge)) / 6 : 0;
        if (speed) { window.scrollBy(0, speed); update(); }
        scrollTimer = requestAnimationFrame(autoScroll);
      };
      scrollTimer = requestAnimationFrame(autoScroll);
      const onMove = (m) => {
        if (m.pointerId !== pid) return;
        m.preventDefault();
        pointerY = m.clientY;
        update();
      };
      const blockScroll = (t) => t.preventDefault();
      const onEnd = (u) => {
        if (u.pointerId !== pid) return;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onEnd);
        window.removeEventListener("pointercancel", onEnd);
        window.removeEventListener("touchmove", blockScroll);
        cancelAnimationFrame(scrollTimer);
        ghost.remove();
        row.classList.remove("dragging");
        // A cancelled gesture (incoming call, etc.) drops nothing.
        commitDrop(u.type === "pointercancel" ? null : target);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onEnd);
      window.addEventListener("pointercancel", onEnd);
      window.addEventListener("touchmove", blockScroll, { passive: false });
      update();
    };
  }

  const checkboxHit = document.createElement("label");
  checkboxHit.className = "todo-check";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = shownDone;
  checkbox.setAttribute("aria-label", `Mark "${todo.title}" ${shownDone ? "not done" : "done"}`);
  checkbox.addEventListener("change", () => {
    // #3: Instant checkbox response - update UI immediately
    const wasChecked = checkbox.checked;
    if (wasChecked) {
      row.classList.add("is-done");
      celebrate(todo.todo_id);
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
      setCollapsed(todo.todo_id, !todo.collapsed);
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

    menu.append(
      menuItem("Copy with subtasks", "copy", () => {
        setActivePanel(null);
        renderTree();
        copyOutline(todo.todo_id);
      })
    );

    menu.append(
      menuItem("Move up", "up", () => reportedFailure(moveTodo(todo.todo_id, "up"))),
      menuItem("Move down", "down", () => reportedFailure(moveTodo(todo.todo_id, "down")))
    );

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

  // Assemble row: checkbox, body, trailing controls
  row.append(checkboxHit, body, trailing);
  if (hasChildren && !isCollapsed) {
    // Stem from this checkbox down to its subtasks (see .todo-stem).
    const stem = document.createElement("span");
    stem.className = "todo-stem";
    stem.setAttribute("aria-hidden", "true");
    row.appendChild(stem);
  }
  li.appendChild(row);

  // Color accent, and a folded detail panel that a tap on the row body opens.
  FieldsUI.decorateRow(row, todo);
  row.addEventListener("click", (e) => {
    if (!FieldsUI.isRowTap(e.target) || row.classList.contains("dragging")) return;
    // A plain tap must not throw away an open editor with typed text.
    if (activePanel && ["add", "split", "edit"].includes(activePanel.mode) &&
        [...document.querySelectorAll("#todo-tree .sheet input, #todo-tree .sheet textarea")]
          .some((f) => f.type !== "date" && f.type !== "time" && f.value.trim())) return;
    setActivePanel("view", todo.todo_id);
    renderTree();
  });

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

  if (isActivePanel("view", todo.todo_id)) {
    li.appendChild(renderViewer(todo, descendantCounts.get(todo.todo_id)));
  }

  if (hasChildren && !isCollapsed) {
    const childList = document.createElement("ul");
    childList.className = "todo-children";
    // Sort children by order_idx (respecting manual reordering), then by urgency
    const children = sinkDone(todo.child_ids
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
      }));
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
    const back = viewerOrigin;
    setActivePanel(back ? "view" : null, back);
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
  const dueTimeInput = renderTimeInput(dueDateInput);

  const submit = () => {
    const title = input.value.trim();
    if (!title) return;
    reportedFailure(saveSplit(todo.todo_id, [title], Due.combine(dueDateInput.value, dueTimeInput.value)));
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
    sheetLabel("Time (optional)", dueTimeInput),
    dueTimeInput,
    renderEditorActions(submit, "Add")
  );
}

// The optional time-of-day next to a date input. It only means something with
// a date, so it is disabled (and cleared) while the date is empty.
function renderTimeInput(dateInput, value = "") {
  const timeInput = document.createElement("input");
  timeInput.type = "time";
  timeInput.value = value;
  const sync = () => {
    timeInput.disabled = !dateInput.value;
    if (!dateInput.value) timeInput.value = "";
  };
  dateInput.addEventListener("input", sync);
  sync();
  return timeInput;
}

// "Repeat every [2] [weeks]" next to the due date. Repeating needs a date to
// count from, so it is disabled (and cleared) while the date is empty.
function renderRepeatControls(dateInput, rule) {
  const row = document.createElement("div");
  row.className = "repeat-row";
  const every = document.createElement("input");
  every.type = "number";
  every.min = "1";
  every.max = "999";
  every.inputMode = "numeric";
  every.setAttribute("aria-label", "Repeat every");
  const unit = document.createElement("select");
  const units = [
    ["", "Never"], ["day", "days"], ["weekday", "weekdays (Mon\u2013Fri)"],
    ["week", "weeks"], ["month", "months"], ["year", "years"],
  ];
  for (const [value, text] of units) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    unit.appendChild(option);
  }
  unit.value = rule ? rule.unit : "";
  every.value = rule ? String(rule.every || 1) : "1";
  const sync = () => {
    // "every 1 day" reads better than "every 1 days".
    const one = (parseInt(every.value, 10) || 1) === 1;
    for (const option of unit.options) {
      const base = { day: "day", week: "week", month: "month", year: "year" }[option.value];
      if (base) option.textContent = one ? base : base + "s";
    }
    if (!dateInput.value) unit.value = "";
    unit.disabled = !dateInput.value;
    every.hidden = !unit.value || unit.value === "weekday";
  };
  dateInput.addEventListener("input", sync);
  unit.addEventListener("change", sync);
  every.addEventListener("input", sync);
  sync();
  row.append(every, unit);
  return {
    row,
    unit,
    value: () => {
      if (!unit.value) return null;
      const n = Math.max(1, Math.min(999, parseInt(every.value, 10) || 1));
      return { unit: unit.value, every: unit.value === "weekday" ? 1 : n };
    },
  };
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
  // An empty date input is blank on iOS, so nobody knows to tap it: show a hint over it.
  const dueField = document.createElement("div");
  dueField.className = "date-field";
  const dueHint = document.createElement("span");
  dueHint.className = "date-field-hint";
  dueHint.textContent = "Pick a date";
  dueHint.setAttribute("aria-hidden", "true");
  dueField.append(dueDateInput, dueHint);
  const syncDueHint = () => dueField.classList.toggle("is-empty", !dueDateInput.value);
  dueDateInput.addEventListener("input", syncDueHint);
  dueDateInput.addEventListener("change", syncDueHint);
  syncDueHint();
  const dueTimeInput = renderTimeInput(dueDateInput, Due.timePart(todo.due_date));
  const repeatControls = renderRepeatControls(dueDateInput, todo.repeat);

  // One compact row; the chip matching the current date shows as selected.
  const shortcutsDiv = document.createElement("div");
  shortcutsDiv.className = "chip-row";
  const shortcuts = [
    { label: "Today", value: getTodayString() },
    { label: "Tomorrow", value: getTomorrowString() },
    { label: "Clear", value: "", plain: true },
  ];
  const chipButtons = shortcuts.map((shortcut) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip" + (shortcut.plain ? " chip-plain" : "");
    btn.textContent = shortcut.label;
    btn.addEventListener("click", () => {
      dueDateInput.value = shortcut.value;
      dueDateInput.dispatchEvent(new Event("input")); // keeps the time field in step
      markChips();
    });
    shortcutsDiv.appendChild(btn);
    return btn;
  });
  function markChips() {
    shortcuts.forEach((shortcut, i) => {
      chipButtons[i].classList.toggle("is-active", !shortcut.plain && dueDateInput.value === shortcut.value);
    });
  }
  dueDateInput.addEventListener("input", markChips);
  markChips();

  const extra = FieldsUI.renderEditFields(todo);
  const buttons = renderEditorActions(() => {
    const title = titleInput.value.trim();
    if (!title) return;
    const result = extra.changes();
    if (result.error) {
      showNotice({ level: "error", message: result.error });
      return;
    }
    reportedFailure(saveEdit(todo.todo_id, title, Due.combine(dueDateInput.value, dueTimeInput.value),
      repeatControls.value(), result.fields));
  });

  const heading = document.createElement("h2");
  heading.className = "sheet-title";
  heading.textContent = "Edit todo";

  const body = document.createElement("div");
  body.className = "sheet-body";
  body.append(
    heading,
    sheetLabel("Title", titleInput),
    titleInput,
    sheetLabel("Due date", dueDateInput),
    dueField,
    shortcutsDiv,
    sheetLabel("Time (optional)", dueTimeInput),
    dueTimeInput,
    sheetLabel("Repeat every", repeatControls.unit),
    repeatControls.row,
    ...extra.nodes
  );
  const screen = renderSheet(body, buttons);
  screen.classList.add("sheet-full");
  return screen;
}

// Full-screen read-only look at one todo; Edit hands off to the edit sheet.
function renderViewer(todo, counts) {
  const add = (parent, tag, className, text) => {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    parent.appendChild(node);
    return node;
  };
  const close = () => {
    setActivePanel(null);
    renderTree();
  };

  const body = document.createElement("div");
  body.className = "sheet-body";
  add(body, "h2", "sheet-title" + (todo.done ? " is-done" : ""), todo.title);

  const facts = document.createElement("dl");
  facts.className = "view-facts";
  const fact = (name, value) => {
    add(facts, "dt", "sheet-label", name);
    add(facts, "dd", "view-value", value);
  };
  fact("Status", todo.done ? "Done" : "Open");
  fact("Due", todo.due_date ? formatDue(todo.due_date) : "No due date");
  if (todo.repeat) fact("Repeats", Due.formatRepeat(todo.repeat));
  if (counts && counts.total) fact("Subtasks", `${counts.done} of ${counts.total} done`);
  if (Fields.isBlocked(todo, model.todosById)) fact("Blocked", "Waiting on an unfinished todo");
  body.appendChild(facts);
  body.appendChild(FieldsUI.renderDetail(todo));

  const buttons = document.createElement("div");
  buttons.className = "sheet-actions";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "btn btn-plain";
  closeBtn.textContent = "Close";
  closeBtn.addEventListener("click", close);
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "btn btn-primary";
  editBtn.textContent = "Edit";
  editBtn.addEventListener("click", () => {
    setActivePanel("edit", todo.todo_id);
    viewerOrigin = todo.todo_id;
    renderTree();
  });
  buttons.append(closeBtn, editBtn);

  const screen = renderSheet(body, buttons);
  screen.classList.add("sheet-full");
  return screen;
}

function renderEmptyState(heading = "All clear", message = "Add your first todo below.") {
  const empty = document.createElement("li");
  empty.className = "todo-empty";
  const badge = document.createElement("div");
  badge.className = "todo-empty-icon";
  badge.appendChild(icon("check"));
  const title = document.createElement("p");
  title.className = "todo-empty-title";
  title.textContent = heading;
  const text = document.createElement("p");
  text.className = "todo-empty-text";
  text.textContent = message;
  empty.append(badge, title, text);
  return empty;
}

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

function renderTree() {
  const treeEl = document.getElementById("todo-tree");
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
// under the composer, so open it upward if there's room above, otherwise
// scroll it into view.
function placeOpenMenu() {
  document.body.classList.remove("menu-room");
  const menu = document.querySelector(".todo-menu-dropdown");
  if (!menu) return;
  const composer = document.getElementById("add-form");
  const composerTop = composer.getClientRects().length
    ? composer.getBoundingClientRect().top
    : window.innerHeight;
  const bottomLimit = composerTop - 8;
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

// ---- Composer: due date chips -----------------------------------------------
// A calendar button opens a row of Today / Tomorrow / Pick date. #add-due (the
// native date input inside the "Pick date" chip) holds the chosen value.

const addForm = document.getElementById("add-form");
const addChips = document.getElementById("add-chips");
const addDueToggle = document.getElementById("add-due-toggle");
const addDue = document.getElementById("add-due");
const addPickText = document.getElementById("add-pick-text");

function renderComposerDue() {
  const value = addDue.value;
  const isToday = value === getTodayString();
  const isTomorrow = value === getTomorrowString();
  addChips.querySelector('[data-due="today"]').classList.toggle("is-active", isToday);
  addChips.querySelector('[data-due="tomorrow"]').classList.toggle("is-active", isTomorrow);
  const custom = !!value && !isToday && !isTomorrow;
  document.getElementById("add-pick").classList.toggle("is-active", custom);
  addPickText.textContent = custom ? formatDue(`${value}T00:00:00`) : "Pick date";
  addDueToggle.classList.toggle("has-value", !!value);
  addDueToggle.setAttribute("aria-label", value ? `Due ${value}. Change due date` : "Set due date");
}

function setComposerChips(open) {
  addChips.hidden = !open;
  addDueToggle.setAttribute("aria-expanded", String(open));
}

addDueToggle.addEventListener("click", () => setComposerChips(addChips.hidden));

addChips.addEventListener("click", (event) => {
  const chip = event.target.closest("[data-due]");
  if (!chip) return;
  const value = chip.dataset.due === "today" ? getTodayString() : getTomorrowString();
  addDue.value = addDue.value === value ? "" : value; // tapping the chosen chip clears it
  renderComposerDue();
});

// The date input sits invisibly over its chip; some desktop browsers only open
// the picker from a small icon, so ask for it explicitly.
document.getElementById("add-pick").addEventListener("click", () => {
  try { addDue.showPicker(); } catch (e) { /* unsupported: the input still works */ }
});
addDue.addEventListener("input", renderComposerDue);

// Tell the CSS how tall the composer is, so padding and popups clear it.
// Measured from the rendered box (incl. the home-indicator padding), and
// re-measured on viewport changes, since iOS resizes the visual viewport when
// the toolbar or keyboard moves.
function measureComposer() {
  const h = Math.ceil(Math.max(addForm.offsetHeight, addForm.getBoundingClientRect().height));
  document.documentElement.style.setProperty("--composer-h", `${h}px`);
}
new ResizeObserver(measureComposer).observe(addForm);
window.addEventListener("resize", measureComposer);
window.addEventListener("orientationchange", measureComposer);
if (window.visualViewport) window.visualViewport.addEventListener("resize", measureComposer);
window.addEventListener("load", measureComposer);
measureComposer();

let createdThisSession = 0;
addForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("add-title");
  const title = input.value.trim();
  if (!title) return;
  const payload = { title };
  if (addDue.value) {
    payload.due_date = addDue.value;
  }
  engine.enqueue({ kind: "create", payload });
  if (window.Mascot) {
    createdThisSession += 1;
    if (createdThisSession === 1 || createdThisSession % 5 === 0) {
      window.Mascot.react(["Added!", "On the list.", "Got it.", "Noted!"][createdThisSession % 4], { key: "added", cooldown: 45000, delay: 700 });
    }
  }
  input.value = "";
  addDue.value = "";
  renderComposerDue();
  setComposerChips(false);
});

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
    const response = await fetch(`${API_BASE}/next`);
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

// ---- Pull to refresh -----------------------------------------------------------
// Drag down from the very top to sync, like tapping the status pill.

const ptr = document.getElementById("ptr");
const PTR_TRIGGER = 64;
const PTR_MAX = 100;
let ptrStart = null;
let ptrDist = 0;
let ptrBusy = false;

function paintPtr(dist, refreshing) {
  ptr.style.setProperty("--ptr-y", `${dist}px`);
  ptr.style.setProperty("--ptr-progress", String(Math.min(dist / PTR_TRIGGER, 1)));
  ptr.classList.toggle("is-ready", dist >= PTR_TRIGGER);
  ptr.classList.toggle("is-refreshing", !!refreshing);
  ptr.classList.toggle("is-pulling", dist > 0 && !refreshing);
}

async function pullRefresh() {
  ptrBusy = true;
  paintPtr(PTR_TRIGGER * 0.75, true);
  const started = performance.now();
  try {
    await engine.flush();
    if (engine.pending() === 0) await reportedFailure(loadAndRender());
    if (activeTab === "next") await reportedFailure(refreshNext());
  } finally {
    // Long enough to register that something happened.
    await new Promise((r) => setTimeout(r, Math.max(0, 600 - (performance.now() - started))));
    ptrBusy = false;
    paintPtr(0, false);
  }
}

document.addEventListener("touchstart", (event) => {
  const blocked = ptrBusy || window.scrollY > 0 || event.touches.length !== 1 ||
    event.target.closest("#event-log, .todo-drag-handle, input, textarea");
  ptrStart = blocked ? null : { x: event.touches[0].clientX, y: event.touches[0].clientY };
  ptrDist = 0;
}, { passive: true });

document.addEventListener("touchmove", (event) => {
  if (!ptrStart) return;
  if (dragState) { // a long-press row drag owns this gesture: never pull-to-refresh after the drop
    ptrStart = null; ptrDist = 0; paintPtr(0, false);
    return;
  }
  const dy = event.touches[0].clientY - ptrStart.y;
  const dx = event.touches[0].clientX - ptrStart.x;
  if (window.scrollY > 0 || dy < 0 || Math.abs(dx) > Math.abs(dy)) {
    if (ptrDist === 0) ptrStart = null; // an ordinary scroll or swipe: stay out of it
    return;
  }
  if (event.cancelable) event.preventDefault(); // no native bounce while we own the gesture
  ptrDist = Math.min(dy * 0.5, PTR_MAX);
  paintPtr(ptrDist, false);
}, { passive: false });

function endPull() {
  if (!ptrStart) return;
  const fire = ptrDist >= PTR_TRIGGER;
  ptrStart = null;
  if (fire) {
    reportedFailure(pullRefresh());
  } else {
    paintPtr(0, false);
  }
  ptrDist = 0;
}
document.addEventListener("touchend", endPull);
document.addEventListener("touchcancel", endPull);

// ---- Event log panel ---------------------------------------------------------

const logPanel = document.getElementById("event-log");
const logText = document.getElementById("event-log-text");

function renderLog() {
  if (logPanel.hidden) return;
  logText.textContent = eventLog.format() || "(no events yet)";
}
eventLog.subscribe(renderLog);

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    // Older/locked-down browsers: fall back to selecting a hidden textarea.
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.cssText = "position:fixed; opacity:0;";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (e) {
    ok = false;
  }
  area.remove();
  return ok;
}

// Reminders (push): a morning digest and a heads-up an hour before timed todos.
// See push.js; every failure is logged and swallowed, never shown as a break.
(() => {
  const btn = document.getElementById("push-toggle");
  if (!btn || !window.Push) return;
  const env = () => ({
    hasSW: "serviceWorker" in navigator,
    hasPush: "PushManager" in window,
    hasNotification: typeof Notification !== "undefined",
    permission: typeof Notification === "undefined" ? "default" : Notification.permission,
    enabled: window.Push.enabled(),
  });
  const LABELS = { unsupported: "Reminders n/a", blocked: "Reminders blocked", off: "Reminders off", on: "Reminders on" };
  const paint = () => {
    const state = window.Push.status(env());
    btn.hidden = state === "unsupported";
    btn.textContent = LABELS[state];
    btn.setAttribute("aria-pressed", String(state === "on"));
    btn.title = state === "blocked" ? "Allow notifications for this app in iOS Settings" : btn.title;
  };
  btn.addEventListener("click", async () => {
    const state = window.Push.status(env());
    try {
      if (state === "on") await window.Push.disable();
      else if (state === "off") logEvent("push", "enable: " + await window.Push.enable());
    } catch (e) {
      logEvent("push", "toggle failed: " + (e && e.message));
    }
    paint();
  });
  paint();
  // Already allowed: quietly keep the token and timezone fresh (travel, token rotation).
  if (window.Push.status(env()) === "on") {
    window.Push.refresh().catch((e) => logEvent("push", "refresh failed: " + (e && e.message)));
  }
})();

document.getElementById("badge-enable").addEventListener("click", async () => {
  try { await Notification.requestPermission(); } catch (e) { /* older signature or blocked */ }
  syncBadgeButton();
  lastBadge = null; // permission just changed: set the badge now
  renderSummary();
});
syncBadgeButton();
// A todo becomes "due today" at midnight without any edit, so recount on return.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") renderSummary();
});

document.getElementById("log-toggle").addEventListener("click", () => {
  logPanel.hidden = !logPanel.hidden;
  renderLog();
  logText.scrollTop = 0;
});
document.getElementById("event-log-close").addEventListener("click", () => {
  logPanel.hidden = true;
});
document.getElementById("event-log-clear").addEventListener("click", () => {
  eventLog.clear();
});
document.getElementById("event-log-copy").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const header = [
    `Todos v${APP_VERSION} event log, newest first`,
    `Copied ${new Date().toString()}`,
    navigator.userAgent,
    `standalone=${isStandalone()} online=${navigator.onLine} visibility=${document.visibilityState}`,
    "",
  ].join("\n");
  const ok = await copyText(header + eventLog.format());
  button.textContent = ok ? "Copied" : "Copy failed";
  setTimeout(() => { button.textContent = "Copy"; }, 1500);
});

// Diagnostics links live behind a quiet "More" toggle in the header.
(() => {
  const toggle = document.getElementById("dev-toggle");
  const tools = document.getElementById("dev-tools");
  if (!toggle || !tools) return;
  toggle.addEventListener("click", () => {
    tools.hidden = !tools.hidden;
    toggle.setAttribute("aria-expanded", String(!tools.hidden));
  });
})();

// Look & feel controls inside the header's "More" panel: completion sound and
// accent color. Per-device preferences (see themes.js).
(() => {
  const soundBtn = document.getElementById("sound-toggle");
  const swatches = document.getElementById("theme-swatches");
  if (!soundBtn || !swatches || !window.Themes || !window.Sound) return;
  const paintSound = () => {
    const on = window.Sound.on();
    soundBtn.textContent = on ? "Sound on" : "Sound off";
    soundBtn.setAttribute("aria-pressed", String(on));
  };
  soundBtn.addEventListener("click", () => {
    window.Sound.set(!window.Sound.on());
    paintSound();
    window.Sound.pop(); // a preview when turning on; silent when turning off
  });
  paintSound();
  const paintSwatches = () => {
    for (const b of swatches.children) b.setAttribute("aria-pressed", String(b.dataset.theme === window.Themes.current()));
  };
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  for (const [id, t] of Object.entries(window.Themes.THEMES)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "theme-swatch";
    b.dataset.theme = id;
    b.setAttribute("aria-label", `${t.name} accent`);
    b.style.setProperty("--sw", (dark ? t.dark : t.light)[0]);
    b.addEventListener("click", () => { window.Themes.set(id); paintSwatches(); });
    swatches.appendChild(b);
  }
  paintSwatches();
})();

// The mascot's idle chatter reflects the list (see mascot.js).
if (window.Mascot) {
  window.Mascot.setMessageSource(() => {
    const all = [...model.todosById.values()];
    if (!all.length) return "A blank slate. Add something!";
    const open = all.filter((t) => !t.done).length;
    const overdue = all.filter(isOverdue).length;
    if (open === 0) return "Nothing left. Go enjoy it \u2728";
    const lines = [
      overdue ? `${overdue} overdue\u2026 one small step?` : null,
      open === 1 ? "Just one thing left!" : `${open} to go. Pick the easiest!`,
      "Tiny steps count.",
      "Psst\u2026 you've got this.",
      doneToday() ? `${doneToday()} done today. Nice!` : "Ready when you are.",
    ].filter(Boolean);
    let i;
    do { i = Math.floor(Math.random() * lines.length); } while (lines.length > 1 && i === window.__mascotLast);
    window.__mascotLast = i;
    return lines[i];
  });
}

// Mascot on/off, alongside the other look-and-feel controls.
(() => {
  const btn = document.getElementById("mascot-toggle");
  if (!btn || !window.Mascot) return;
  const paint = () => {
    const on = window.Mascot.enabled();
    btn.textContent = on ? "Mascot on" : "Mascot off";
    btn.setAttribute("aria-pressed", String(on));
  };
  btn.addEventListener("click", () => {
    window.Mascot.setEnabled(!window.Mascot.enabled());
    paint();
    if (window.Mascot.enabled()) window.Mascot.peek({ text: "Hi! I'm Nudge \ud83d\udc4b" });
  });
  paint();
})();

// "Shake to summon" the mascot. Android/desktop listen automatically; iOS needs
// this tap to grant motion access; after a relaunch Mascot re-asks on the first tap.
(() => {
  const btn = document.getElementById("shake-toggle");
  if (!btn || !window.Mascot || !window.Mascot.shake.supported()) return;
  const paint = () => {
    btn.hidden = false;
    btn.textContent = window.Mascot.shake.active() ? "Shake on" : "Shake to summon";
    btn.setAttribute("aria-pressed", String(window.Mascot.shake.active()));
  };
  // After a relaunch, Mascot re-requests motion access on the first tap.
  window.addEventListener("shake-rearm", (e) => {
    logEvent("shake", "re-armed on first tap: " + (e && e.detail));
    paint();
  });
  btn.addEventListener("click", async () => {
    if (!window.Mascot.shake.active()) {
      const result = await window.Mascot.shake.request();
      btn.textContent = result === "denied" ? "Shake blocked" : btn.textContent;
      if (result === "granted") window.Mascot.peek({ text: "Shake me anytime! \ud83d\udc4b" });
    }
    if (btn.textContent !== "Shake blocked") paint();
  });
  paint();
})();

// Shake feedback: while the More panel is open, the Shake button shows how hard
// the phone is moving, so a too-gentle shake (or missing permission) is visible.
(() => {
  const btn = document.getElementById("shake-toggle");
  if (!btn || !window.Mascot || !window.Mascot.shake.supported()) return;
  let peak = 0, timer = null;
  window.Mascot.shake.onPeak((dev) => {
    if (dev <= peak) return;
    peak = dev;
    if (btn.hidden || btn.offsetParent === null) return;
    btn.textContent = `Shake on \u00b7 ${dev.toFixed(0)}`;
    clearTimeout(timer);
    timer = setTimeout(() => { peak = 0; btn.textContent = "Shake on"; }, 1500);
  });
})();

// Backup summon: tap the "Todos" title three times.
(() => {
  const title = document.querySelector(".app-title");
  if (!title || !window.Mascot) return;
  let taps = [];
  title.addEventListener("click", () => {
    const now = Date.now();
    taps = taps.filter((t) => now - t < 900).concat(now);
    if (taps.length >= 3) { taps = []; window.Mascot.peek({}); }
  });
})();

// ---- more mascot reactions -------------------------------------------------

// Welcome back after a real absence, and a once-a-day greeting.
(() => {
  if (!window.Mascot) return;
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt > 20 * 60 * 1000) {
      const open = [...model.todosById.values()].filter((t) => !t.done).length;
      window.Mascot.react(open ? `Welcome back! ${open} open.` : "Welcome back! All clear.", { key: "back", cooldown: 600000, delay: 1200 });
    }
    hiddenAt = 0;
  });

  const KEY = "now.greeted";
  const today = new Date().toDateString();
  let greeted = null;
  try { greeted = localStorage.getItem(KEY); } catch (_) { /* unavailable */ }
  if (greeted !== today) {
    setTimeout(() => {
      const all = [...model.todosById.values()];
      if (!all.length) return; // the list hasn't loaded, or is empty: try tomorrow
      const hour = new Date().getHours();
      const hello = hour < 5 ? "Burning the midnight oil?" : hour < 12 ? "Good morning!" : hour < 18 ? "Good afternoon!" : "Good evening!";
      const open = all.filter((t) => !t.done).length;
      const overdue = all.filter(isOverdue).length;
      const tail = overdue ? ` ${overdue} overdue.` : open ? ` ${open} to do.` : " Nothing to do!";
      window.Mascot.react(hello + tail, { key: "greet", cooldown: 0, delay: 0 });
      try { localStorage.setItem(KEY, today); } catch (_) { /* unavailable */ }
    }, 4000);
  }
})();

// Milestones: 3, 5, 10, 20... done today (see doneToday()).
function reactToDoneCount(n, todo) {
  if (!window.Mascot) return;
  if ([3, 5, 10, 15, 20, 30].includes(n)) {
    const lines = { 3: "Three down. On a roll!", 5: "Five done today. Nice!", 10: "Ten! You're unstoppable.", 15: "Fifteen?! Legend.", 20: "Twenty. Wow.", 30: "Thirty. Take a bow." };
    window.Mascot.react(lines[n], { key: `milestone${n}`, cooldown: 3600000, delay: 1600 });
  } else if (todo && todo.repeat) {
    window.Mascot.react("Done. See you next time! \ud83d\udd01", { key: "repeat", cooldown: 30000, delay: 1600 });
  }
}
