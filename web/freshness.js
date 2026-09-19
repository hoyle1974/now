// Decides when a window should re-download the todo tree because another
// window (or device) wrote to it. It never polls on a timer: the app calls
// check() when the window regains focus or visibility, and poke() when
// something that was blocking a refresh (unsent edits, an open editor) clears.
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Freshness = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function create({ engine, fetchRev, refresh, editorOpen = () => false, now = Date.now, minGapMs = 30000 }) {
    // Starts "just checked": the page load already fetched the tree.
    let lastCheck = now();
    let running = false;
    // True when a check or refresh was held back and should run on the next poke.
    let deferred = false;

    async function attempt() {
      if (running) return;
      running = true;
      try {
        // Unsent edits first: a refresh would race them, and the queue draining
        // is what pokes us again.
        if (engine.pending() > 0) {
          deferred = true;
          return;
        }
        if (!engine.isStale()) {
          lastCheck = now();
          let rev;
          try {
            rev = await fetchRev();
          } catch (e) {
            deferred = false; // offline: the next focus will try again
            return;
          }
          engine.noteRemoteRev(rev);
        }
        if (!engine.isStale()) {
          deferred = false;
          return;
        }
        // A refresh re-renders the list and would wipe half-typed text.
        if (editorOpen()) {
          deferred = true;
          return;
        }
        deferred = false;
        try {
          await refresh();
        } catch (e) {
          // Still stale; the next trigger retries.
        }
      } finally {
        running = false;
      }
    }

    // A focus / visibility / online event. At most one server check per minGapMs
    // unless we already know we're stale.
    async function check() {
      if (running) return;
      if (!engine.isStale() && now() - lastCheck < minGapMs) return;
      await attempt();
    }

    // Something that was blocking us cleared: continue only if a check or
    // refresh is actually waiting.
    async function poke() {
      if (running || (!deferred && !engine.isStale())) return;
      await attempt();
    }

    return { check, poke };
  }

  return { create };
});
