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

  const sfx = (name) => { if (root.Sound && root.Sound.sfx) root.Sound.sfx(name); };
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
      sfx("giggle");
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
      if (n % 2 === 0) sfx("blink");
      n++;
      setTimeout(tick, n % 2 ? 130 : 260);
    };
    setTimeout(tick, 650);
  }

  // The bubble is centred on him; near a screen edge that would push it off, so
  // shift it inward (the tail keeps pointing at him, see --bubble-shift in CSS).
  function keepBubbleOnScreen() {
    const margin = 10;
    const vw = document.documentElement.clientWidth;
    bubble.style.setProperty("--bubble-shift", "0px");
    const cx = el.getBoundingClientRect().left + el.offsetWidth / 2;
    const w = bubble.offsetWidth;
    const left = cx - w / 2;
    const clamped = Math.min(Math.max(left, margin), Math.max(margin, vw - margin - w));
    bubble.style.setProperty("--bubble-shift", `${Math.round(clamped - left)}px`);
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
    if (msg) keepBubbleOnScreen();
    el.classList.add("is-up");
    sfx(cheer ? "cheer" : "peek");
    if (msg && !cheer) setTimeout(() => up && sfx("beep"), 700);
    blink(2);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, cheer ? STAY + 1400 : STAY + (msg ? 900 : 0));
  }

  function hide() {
    if (!up) return;
    up = false;
    clearTimeout(hideTimer);
    sfx("hide");
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

  // ---- shake to summon ----
  // A shake is three hard swings of the accelerometer within 1.4 seconds. iOS only
  // delivers motion events after a permission prompt that must come from a tap
  // (see request, wired to the More panel's Shake button).
  let shakeOn = false, spikes = [], lastShake = 0, lastSpike = 0, peakListener = null;
  const GRAVITY = 9.81;
  // Distance of each reading from resting gravity: still is ~0, a hard shake
  // swings it by 10+ m/s2. Works even at 60 readings a second, where the change
  // between two consecutive readings stays small.
  function onMotion(e) {
    const a = e.accelerationIncludingGravity;
    if (!a || a.x == null) return;
    const dev = Math.abs(Math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z) - GRAVITY);
    if (peakListener) peakListener(dev);
    if (dev < 7) return; // ordinary movement
    const now = Date.now();
    if (now - lastSpike < 100) return; // one swing counts once
    lastSpike = now;
    spikes = spikes.filter((t) => now - t < 1400);
    spikes.push(now);
    if (spikes.length >= 3 && now - lastShake > 3000) {
      spikes = [];
      lastShake = now;
      summon();
    }
  }
  function summon() {
    if (!enabled() || up) return;
    if (root.navigator && root.navigator.vibrate) root.navigator.vibrate(15);
    show({ text: message() });
  }
  const shakeSupported = () => typeof root.DeviceMotionEvent !== "undefined";
  const needsPermission = () =>
    shakeSupported() && typeof root.DeviceMotionEvent.requestPermission === "function";
  async function requestShake() {
    if (!shakeSupported()) return "unsupported";
    if (needsPermission()) {
      try {
        if ((await root.DeviceMotionEvent.requestPermission()) !== "granted") return "denied";
      } catch (_) { return "denied"; }
    }
    if (!shakeOn) { root.addEventListener("devicemotion", onMotion); shakeOn = true; }
    return "granted";
  }
  // Android and desktop need no permission: listen right away.
  if (typeof document !== "undefined" && shakeSupported() && !needsPermission()) requestShake();

  root.Mascot = {
    shake: { onPeak(fn) { peakListener = fn; }, supported: shakeSupported, needsPermission, request: requestShake, active: () => shakeOn, _onMotion: onMotion },
    enabled,
    setEnabled(on) { write(on ? "1" : "0"); if (!on) hide(); else schedule(); },
    peek: (opts) => show(opts),
    cheer: () => show({ cheer: true, text: "All done! Look at you ✨" }),
    hide,
    setMessageSource(fn) { source = fn; },
  };
  if (typeof document !== "undefined") init();
})(typeof window !== "undefined" ? window : globalThis);
