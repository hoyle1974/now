// Event log panel, reminders, badge, and the More panel's look, mascot and shake controls.
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).
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

// Reminders (push): one morning digest of what is due today or overdue.
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

// Calendar feed: a private read-only ICS link (see docs/okf/features/calendar-feed.md).
// The token never ships in the page: the signed-in app asks the server for the path.
(async () => {
  const row = document.getElementById("calendar-row");
  if (!row) return;
  let path = null;
  try {
    const response = await fetch("/calendar/link");
    const info = response.ok ? await response.json() : null;
    if (info && info.enabled && info.path) path = info.path;
  } catch (e) { /* offline or signed out: the row stays hidden */ }
  if (!path) return;
  row.hidden = false;
  const copyBtn = document.getElementById("calendar-copy");
  const subBtn = document.getElementById("calendar-subscribe");
  const flash = (btn, text, label) => {
    btn.textContent = text;
    setTimeout(() => { btn.textContent = label; }, 2500);
  };
  const copyLink = async (btn, label) => {
    const ok = await copyText(`${window.location.origin}${path}`);
    flash(btn, ok ? "Copied" : "Copy failed", label);
    return ok;
  };
  subBtn.addEventListener("click", () => {
    logEvent("calendar", "subscribe");
    window.location.href = `webcal://${window.location.host}${path}`;
    // iOS Home Screen apps often ignore webcal: links. If we are still here, the
    // link was not opened, so copy it for Calendar > Add Subscription instead.
    setTimeout(() => {
      if (document.visibilityState === "visible") {
        copyLink(subBtn, "Subscribe").then((ok) => { if (ok) flash(subBtn, "Link copied", "Subscribe"); });
      }
    }, 1500);
  });
  copyBtn.addEventListener("click", () => copyLink(copyBtn, "Copy link"));
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
