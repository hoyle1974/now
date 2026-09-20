// "Nudge", a small blob who peeks up from behind the add bar when you've been
// idle for a while, blinks, says something, and ducks away again. Pure
// decoration: pointer-events only while visible, never over an open sheet,
// menu or keyboard, and skipped entirely for reduced-motion.
(function (root) {
  const KEY = "now.mascot";
  const IDLE_MIN = 25000;   // ms of no interaction before a peek is possible
  const IDLE_SPAN = 30000;  // plus up to this much, at random
  const STAY = 3400;        // how long he stays up

  const read = () => { try { return root.localStorage.getItem(KEY); } catch (_) { return null; } };
  const write = (v) => { try { root.localStorage.setItem(KEY, v); } catch (_) { /* unavailable */ } };
  const enabled = () => read() !== "0";
  const reduced = () => root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const SVG = `
<svg viewBox="0 0 80 64" width="80" height="64" aria-hidden="true">
  <g class="m-antenna"><line x1="40" y1="14" x2="40" y2="4" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
    <circle class="m-bulb" cx="40" cy="4" r="4.5" fill="#ffcc00"/></g>
  <path d="M6 64 V38 C6 22 20 12 40 12 C60 12 74 22 74 38 V64 Z" fill="currentColor"/>
  <ellipse cx="18" cy="46" rx="6" ry="4" fill="#ff8fb1" opacity=".55"/>
  <ellipse cx="62" cy="46" rx="6" ry="4" fill="#ff8fb1" opacity=".55"/>
  <g class="m-eyes">
    <circle cx="28" cy="36" r="7.5" fill="#fff"/><circle cx="52" cy="36" r="7.5" fill="#fff"/>
    <circle class="m-pupil" cx="29.5" cy="37" r="3.6" fill="#1c1c1e"/><circle class="m-pupil" cx="53.5" cy="37" r="3.6" fill="#1c1c1e"/>
  </g>
  <g class="m-happy" fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round">
    <path d="M21 38 Q28 30 35 38"/><path d="M45 38 Q52 30 59 38"/></g>
  <path class="m-mouth" d="M33 49 Q40 56 47 49" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
</svg>`;

  let el, bubble, idleTimer, hideTimer, up = false, source = null, lastMsg = -1;

  function build() {
    if (el) return;
    el = document.createElement("div");
    el.className = "mascot";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = `<div class="mascot-bubble" hidden></div><div class="mascot-body">${SVG}</div>`;
    bubble = el.querySelector(".mascot-bubble");
    el.addEventListener("click", () => {
      if (!up) return;
      el.classList.add("is-giggle");
      if (root.Sparkle) {
        const r = el.getBoundingClientRect();
        root.Sparkle.burst(r.left + r.width / 2, r.top + 20, 10);
      }
      if (root.navigator && root.navigator.vibrate) root.navigator.vibrate(8);
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, 900);
    });
    document.body.appendChild(el);
  }

  const quiet = () =>
    document.hidden ||
    document.querySelector(".sheet, .todo-menu-dropdown, .lightbox, .search-overlay") ||
    (document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) ||
    !document.getElementById("error").hidden;

  function message() {
    const fromApp = source && source();
    if (fromApp) return fromApp;
    return "Psst… you've got this.";
  }

  function blink(times) {
    let n = 0;
    const tick = () => {
      if (!up || n >= times * 2) return;
      el.classList.toggle("is-blink", n % 2 === 0);
      n++;
      setTimeout(tick, n % 2 ? 130 : 260);
    };
    setTimeout(tick, 650);
  }

  function show({ cheer = false, text } = {}) {
    if (!enabled() || reduced() || up) return;
    build();
    up = true;
    el.style.setProperty("--x", cheer ? "50%" : ["18%", "50%", "82%"][Math.floor(Math.random() * 3)]);
    el.classList.remove("is-giggle", "is-blink");
    el.classList.toggle("is-cheer", cheer);
    const msg = text || (Math.random() < 0.6 || cheer ? message() : "");
    bubble.hidden = !msg;
    bubble.textContent = msg;
    el.classList.add("is-up");
    blink(2);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, cheer ? STAY + 1400 : STAY + (msg ? 900 : 0));
  }

  function hide() {
    if (!up) return;
    up = false;
    clearTimeout(hideTimer);
    el.classList.remove("is-up");
    schedule();
  }

  function schedule() {
    clearTimeout(idleTimer);
    if (!enabled() || reduced()) return;
    idleTimer = setTimeout(() => {
      if (quiet()) return schedule();
      show();
    }, IDLE_MIN + Math.random() * IDLE_SPAN);
  }

  // Any interaction resets the idle clock, and sends a visible mascot home.
  function activity() {
    if (up && !el.matches(":active")) hide();
    else if (!up) schedule();
  }

  function init() {
    for (const ev of ["pointerdown", "keydown", "scroll", "touchstart"]) {
      root.addEventListener(ev, activity, { passive: true, capture: true });
    }
    document.addEventListener("visibilitychange", () => (document.hidden ? hide() : schedule()));
    schedule();
  }

  root.Mascot = {
    enabled,
    setEnabled(on) { write(on ? "1" : "0"); if (!on) hide(); else schedule(); },
    peek: (opts) => show(opts),
    cheer: () => show({ cheer: true, text: "All done! Look at you ✨" }),
    hide,
    setMessageSource(fn) { source = fn; },
  };
  if (typeof document !== "undefined") init();
})(typeof window !== "undefined" ? window : globalThis);
