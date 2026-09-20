// Decides when a window should re-download the todo tree because another
// window (or device) wrote to it. There is no polling timer: the app calls
// check() when the window comes back (focus, visibility, pageshow, online), and
// poke() when something that was blocking a refresh (unsent edits, an open
// editor) clears. No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Freshness = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function create({
    engine, fetchRev, refresh,
    editorOpen = () => false,
    now = Date.now,
    // At most one server check per minGapMs when the window only flickered...
    minGapMs = 30000,
    // ...but a window that was away at least this long always checks.
    awayBypassMs = 5000,
    // A phone that just woke often has no network for a second or two, so a
    // failed check is retried (only while the window is still active), twice.
    retryDelaysMs = [2000, 6000],
    isActive = () => true,
    // The page's own code version. fetchRev may return {rev, version}; when the
    // server's version differs this page is running old code, so reload it.
    // reloadGuard remembers the last version we reloaded for, so a browser that
    // keeps serving cached code can't put the page into a reload loop.
    appVersion = null,
    reload = () => {},
    reloadGuard = { get: () => null, set: () => {} },
    // Reports what we're doing so the UI can say so: "idle" | "checking" |
    // "refreshing" | "retrying" (no network yet, will try again) | "waiting"
    // (changes found but held back by an open editor) | "unreachable".
    onPhase = () => {},
    // Diagnostics (kind, short detail) for the on-device event log.
    onLog = () => {},
    timers = { setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (t) => clearTimeout(t) },
  }) {
    // Starts "just checked": the page load already fetched the tree.
    let lastCheck = now();
    let running = false;
    // True when a check or refresh was held back and should run on the next poke.
    let deferred = false;
    let retryTimer = null;
    let retryCount = 0;
    // Set when the server reports different code than this page is running;
    // kept across a held (editor open) attempt so poke() can finish the reload.
    let newVersion = null;

    function clearRetry() {
      if (retryTimer !== null) {
        timers.clearTimeout(retryTimer);
        retryTimer = null;
      }
    }

    // Returns whether another attempt is scheduled.
    function scheduleRetry() {
      if (retryCount >= retryDelaysMs.length || !isActive()) {
        onLog("retry", retryCount >= retryDelaysMs.length ? "giving up" : "not scheduled, page not visible");
        return false;
      }
      const delay = retryDelaysMs[retryCount++];
      onLog("retry", `in ${delay}ms (#${retryCount})`);
      retryTimer = timers.setTimeout(async () => {
        retryTimer = null;
        if (running || !isActive()) {
          onLog("retry", "dropped, page not visible"); // backgrounded meanwhile: stay quiet
          return;
        }
        await attempt();
      }, delay);
      return true;
    }

    async function attempt() {
      if (running) return;
      running = true;
      try {
        // Unsent edits first: a refresh would race them, and the queue draining
        // is what pokes us again.
        if (engine.pending() > 0) {
          deferred = true;
          onLog("defer", `${engine.pending()} unsent edit(s), check later`);
          return;
        }
        if (!engine.isStale()) {
          let rev;
          let version = null;
          onPhase("checking");
          const startedAt = now();
          try {
            const res = await fetchRev();
            if (res !== null && typeof res === "object") {
              rev = res.rev;
              version = res.version ?? null;
            } else {
              rev = res;
            }
          } catch (e) {
            onLog("rev-fail", `${e && e.message ? e.message : e} (${now() - startedAt}ms)`);
            // No network yet (e.g. just after unlocking a phone). This attempt
            // must not count as a check, or it would block the retries and the
            // `online` event behind the debounce.
            deferred = false;
            onPhase(scheduleRetry() ? "retrying" : "unreachable");
            return;
          }
          lastCheck = now();
          retryCount = 0;
          const known = engine.knownRev ? engine.knownRev() : null;
          onLog("rev", `server ${rev}, known ${known ?? "?"}${known === null || rev > known ? " -> stale" : ""} (${now() - startedAt}ms)`);
          if (appVersion !== null && version !== null && version !== appVersion) {
            newVersion = version;
          } else {
            engine.noteRemoteRev(rev);
          }
        }
        if (newVersion !== null) {
          // Old code would misread newer data, so reload instead of refreshing.
          if (reloadGuard.get() === newVersion) {
            onLog("version", `server ${newVersion}, page ${appVersion}: already reloaded once, staying`);
            newVersion = null;
          } else if (editorOpen()) {
            deferred = true;
            onPhase("waiting");
            onLog("waiting", `new version ${newVersion}, reload held (editor open)`);
            return;
          } else {
            onLog("version", `server ${newVersion}, page ${appVersion}: reloading`);
            reloadGuard.set(newVersion);
            newVersion = null;
            reload();
            return;
          }
        }
        if (!engine.isStale()) {
          deferred = false;
          onPhase("idle");
          return;
        }
        // A refresh re-renders the list and would wipe half-typed text.
        if (editorOpen()) {
          deferred = true;
          onPhase("waiting");
          onLog("waiting", "editor open, refresh held");
          return;
        }
        deferred = false;
        onPhase("refreshing");
        onLog("refresh", "start");
        const refreshStart = now();
        try {
          await refresh();
          onLog("refresh", `ok (${now() - refreshStart}ms)`);
          onPhase("idle");
        } catch (e) {
          // Still stale; the next trigger retries.
          onLog("refresh-fail", e && e.message ? e.message : String(e));
          onPhase("unreachable");
        }
      } finally {
        running = false;
      }
    }

    // The window came back. awayMs is how long it was away (0 if unknown);
    // force skips the debounce (e.g. connectivity just returned).
    async function check({ awayMs = 0, force = false } = {}) {
      onLog("check", `away=${Math.round(awayMs)}ms force=${force}`);
      if (running) {
        onLog("skip", "another check is running");
        return;
      }
      const sinceLast = now() - lastCheck;
      const debounced = sinceLast < minGapMs && awayMs < awayBypassMs;
      if (!force && !engine.isStale() && debounced) {
        onLog("skip", `debounced (${sinceLast}ms since last check)`);
        return;
      }
      // Only a check that actually proceeds supersedes a pending retry; a
      // debounced one must leave it, or "Reconnecting…" would never resolve.
      clearRetry();
      retryCount = 0;
      await attempt();
    }

    // Something that was blocking us cleared: continue only if a check or
    // refresh is actually waiting.
    async function poke() {
      if (running || (!deferred && !engine.isStale())) return;
      onLog("poke", `deferred=${deferred} stale=${engine.isStale()}`);
      await attempt();
    }

    return { check, poke };
  }

  return { create };
});
