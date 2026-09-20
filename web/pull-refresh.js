// Pull-to-refresh.
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).

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

