// The one toast: a single message line (the #error element) with an optional action
// button, latest message wins. Owns its timers, so no writer can clobber (or later clear)
// another's message. DOM access goes through the element handed to create(), so it runs
// under `node --test` with a stand-in.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Toast = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const INFO_TTL_MS = 5000;

  // el: the toast element. deps (tests): timers { setTimeout, clearTimeout }, button() -> element.
  function create(el, deps = {}) {
    const timers = deps.timers || { setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (t) => clearTimeout(t) };
    const makeButton = deps.button || (() => document.createElement("button"));
    let timer = null;
    let shown = null; // { source, kind } of the message on screen

    function hide() {
      timers.clearTimeout(timer);
      timer = null;
      shown = null;
      el.onclick = null;
      el.hidden = true;
    }

    // opts: message; level "info" (default, calm) | "error"; ttl ms (info defaults to 5s,
    // error stays until tapped unless ttl is given); action { label, run } adds a button
    // that runs once and hides the toast; source / kind tag the message so its owner can
    // take it down later (hideSource / hideKind) without touching anyone else's.
    function show({ message, level = "info", ttl, action, source = null, kind = null }) {
      timers.clearTimeout(timer);
      el.onclick = null;
      if (kind) el.dataset.kind = kind; else delete el.dataset.kind;
      el.classList.toggle("toast--calm", level !== "error");
      el.hidden = false;
      el.textContent = action ? message + " · " : message;
      if (action) {
        const button = makeButton();
        button.textContent = action.label;
        button.className = "toast-action";
        button.onclick = () => {
          hide();
          action.run();
        };
        el.appendChild(button);
      } else if (level === "error") {
        el.onclick = hide; // a permanent failure stays until dismissed
      }
      shown = { source, kind };
      const life = ttl !== undefined ? ttl : level === "error" && !action ? null : INFO_TTL_MS;
      timer = life === null ? null : timers.setTimeout(hide, life);
    }

    return {
      show,
      hide,
      hideSource: (source) => { if (shown && shown.source === source) hide(); },
      hideKind: (kind) => { if (shown && shown.kind === kind) hide(); },
    };
  }

  return { create };
});
