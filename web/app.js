// Main UI, in ten parts loaded in this order (see index.html): app.js (this file: API,
// sync glue, todo actions), ui-helpers, row-interactions, render-node, editors,
// tree-view, composer, next-up-ui, pull-refresh, more-panel. They share one global
// scope, so a part may use anything declared in an earlier part at load time and
// anything declared in any part at run time. APP_VERSION below is read by the server.
const API_BASE = "/todos";
const APP_VERSION = "60";

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

