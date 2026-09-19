// A small on-device event log for diagnosing sync/refresh behaviour, especially
// on a phone where the page is suspended and killed while the screen is locked.
// Entries are kept in localStorage so they survive a reload, capped at `max`.
// Only event names and short details are recorded, never todo titles.
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.EventLog = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const MAX_DETAIL = 200;

  function detailText(detail) {
    if (detail === undefined || detail === null) return "";
    if (typeof detail === "string") return detail.slice(0, MAX_DETAIL);
    try {
      return JSON.stringify(detail).slice(0, MAX_DETAIL);
    } catch (e) {
      return String(detail).slice(0, MAX_DETAIL);
    }
  }

  // "+250ms", "+2.3s", "+2m05s", "+1h02m": how long since the previous entry.
  // A large gap between two events is how a suspended page shows up.
  function formatGap(ms) {
    if (ms < 1000) return `+${Math.round(ms)}ms`;
    if (ms < 60000) return `+${(ms / 1000).toFixed(1)}s`;
    const totalSeconds = Math.floor(ms / 1000);
    if (ms < 3600000) {
      const m = Math.floor(totalSeconds / 60);
      const sec = String(totalSeconds % 60).padStart(2, "0");
      return `+${m}m${sec}s`;
    }
    const h = Math.floor(totalSeconds / 3600);
    const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
    return `+${h}h${m}m`;
  }

  function pad(n, width = 2) {
    return String(n).padStart(width, "0");
  }

  function formatTime(t) {
    const d = new Date(t);
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
  }

  function create({ storage = null, key = "todo-event-log", max = 300, now = Date.now } = {}) {
    let items = [];
    const listeners = new Set();

    try {
      const raw = storage && storage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) items = parsed.slice(-max);
    } catch (e) {
      items = [];
    }

    function save() {
      try {
        if (storage) storage.setItem(key, JSON.stringify(items));
      } catch (e) {
        // Storage blocked or full: keep logging in memory for this page.
      }
    }

    function notify() {
      for (const fn of listeners) {
        try { fn(); } catch (e) { /* a broken listener must not break logging */ }
      }
    }

    function log(kind, detail) {
      items.push({ t: now(), k: kind, d: detailText(detail) });
      if (items.length > max) items.splice(0, items.length - max);
      save();
      notify();
    }

    function clear() {
      items = [];
      save();
      notify();
    }

    // Newest first, each line showing the gap since the entry before it.
    function format() {
      const lines = [];
      for (let i = items.length - 1; i >= 0; i--) {
        const e = items[i];
        const gap = i > 0 ? formatGap(e.t - items[i - 1].t) : "";
        lines.push(`${formatTime(e.t)} ${gap.padStart(8)} ${e.k.padEnd(11)} ${e.d}`.trimEnd());
      }
      return lines.join("\n");
    }

    function subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    }

    return { log, clear, format, subscribe, entries: () => items.slice() };
  }

  return { create, formatGap };
});
