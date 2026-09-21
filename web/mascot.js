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
  <g class="m-arm m-arm-l"><line x1="6" y1="48" x2="6" y2="62" stroke="currentColor" stroke-width="7" stroke-linecap="round"/></g>
  <g class="m-arm m-arm-r"><line x1="74" y1="48" x2="74" y2="62" stroke="currentColor" stroke-width="7" stroke-linecap="round"/></g>
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

  // ---- eyes ----
  // Pupils drift in SVG units (eye white radius 7.5, pupil 3.6, so 3 is the edge).
  // Two sources add up: a tilt of the phone (gravity pulls them down-hill) and
  // random glances; a tap on him pulls them toward the finger for a moment.
  const GAZE_MAX = 3;
  const clampGaze = (v) => Math.max(-GAZE_MAX, Math.min(GAZE_MAX, v));
  // ax/ay: accelerationIncludingGravity. Android reads the reaction to gravity, iOS the
  // opposite sign, so flip for iOS (flip = true). Upright phone: pupils rest a touch low.
  function gazeFromTilt(ax, ay, flip) {
    const s = flip ? -1 : 1;
    return { x: clampGaze((-s * ax / GRAVITY) * GAZE_MAX * 1.5), y: clampGaze((s * ay / GRAVITY) * GAZE_MAX * 0.6) };
  }
  let tilt = { x: 0, y: 0 }, glance = { x: 0, y: 0 }, lookTimer = null, lookLockUntil = 0;
  function applyGaze() {
    if (!el) return;
    el.style.setProperty("--gx", clampGaze(tilt.x + glance.x).toFixed(2));
    el.style.setProperty("--gy", clampGaze(tilt.y + glance.y).toFixed(2));
  }
  const GLANCES = [[-1, 0], [1, 0], [0, -0.7], [0, 0], [-1, 0.6], [1, 0.6], [0.6, -0.5]];
  function lookAround() {
    clearTimeout(lookTimer);
    if (!up) return;
    if (Date.now() >= lookLockUntil) {
      const g = GLANCES[Math.floor(Math.random() * GLANCES.length)];
      const amp = shakeOn ? 1.2 : GAZE_MAX; // tilt already moves them; keep glances small then
      glance = { x: g[0] * amp, y: g[1] * amp };
      applyGaze();
    }
    lookTimer = setTimeout(lookAround, 700 + Math.random() * 1300);
  }
  function lookAt(clientX, clientY) {
    const r = el.getBoundingClientRect();
    const dx = clientX - (r.left + r.width / 2), dy = clientY - (r.top + r.height / 2);
    const d = Math.hypot(dx, dy) || 1;
    glance = { x: clampGaze((dx / d) * GAZE_MAX), y: clampGaze((dy / d) * GAZE_MAX) };
    lookLockUntil = Date.now() + 900;
    applyGaze();
  }

  const sfx = (name) => { if (root.Sound && root.Sound.sfx) root.Sound.sfx(name); };
  // The unprompted idle pop-up (and its blink, beep and exit) is near-silent;
  // cheers, happy pops, and anything after you tap him keep the normal voice.
  let soft = false;
  const voice = (name) => sfx(soft ? name + "Soft" : name);
  let el, bubble, idleTimer, hideTimer, up = false, source = null, lastMsg = -1;

  function build() {
    if (el) return;
    el = document.createElement("div");
    el.className = "mascot";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = `<div class="mascot-bubble" hidden></div><div class="mascot-body">${SVG}</div>`;
    bubble = el.querySelector(".mascot-bubble");
    el.addEventListener("click", (e) => {
      if (!up) return;
      if (e && e.clientX != null) lookAt(e.clientX, e.clientY);
      el.classList.add("is-giggle");
      soft = false;
      sfx("giggle");
      if (root.Sparkle) {
        const r = el.getBoundingClientRect();
        root.Sparkle.burst(r.left + r.width / 2, r.top + 20, 10);
      }
      if (root.navigator && root.navigator.vibrate) root.navigator.vibrate(8);
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, 900);
    });
    // Child of the composer, so he is anchored to it by layout (no measured height to
    // go stale under iOS safe-area / toolbar changes).
    (document.getElementById("add-form") || document.body).appendChild(el);
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
      if (n % 2 === 0) voice("blink");
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

  function show({ cheer = false, happy = false, text, idle = false } = {}) {
    if (!enabled() || reduced() || up) return;
    build();
    up = true;
    el.style.setProperty("--x", cheer ? "50%" : ["18%", "50%", "82%"][Math.floor(Math.random() * 3)]);
    el.classList.remove("is-giggle", "is-blink", "is-wave-l", "is-wave-r");
    el.classList.toggle("is-cheer", cheer || happy);
    const msg = text || (Math.random() < 0.6 || cheer ? message() : "");
    bubble.hidden = !msg;
    bubble.textContent = msg;
    if (msg) keepBubbleOnScreen();
    // Sometimes wave, with the arm away from the nearest screen edge (toward the middle).
    if (!cheer && !happy && Math.random() < 0.5) {
      const cx = el.getBoundingClientRect().left + el.offsetWidth / 2;
      const vw = document.documentElement.clientWidth;
      const mid = Math.abs(cx - vw / 2) < 4;
      el.classList.add((mid ? Math.random() < 0.5 : cx < vw / 2) ? "is-wave-r" : "is-wave-l");
    }
    el.classList.add("is-up");
    soft = idle && !cheer && !happy;
    sfx(cheer ? "cheer" : happy ? "giggle" : soft ? "peekSoft" : "peek");
    if (msg && !cheer) setTimeout(() => up && voice("beep"), 700);
    blink(2);
    glance = { x: 0, y: 0 };
    lookLockUntil = 0;
    applyGaze();
    lookTimer = setTimeout(lookAround, 900);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, cheer ? STAY + 1400 : STAY + (msg ? 900 : 0));
  }

  function hide() {
    if (!up) return;
    up = false;
    clearTimeout(hideTimer);
    clearTimeout(lookTimer);
    voice("hide");
    el.classList.remove("is-up");
    schedule();
  }

  function schedule() {
    clearTimeout(idleTimer);
    if (!enabled() || reduced()) return;
    idleTimer = setTimeout(() => {
      if (quiet()) return schedule();
      show({ idle: true });
    }, IDLE_MIN + Math.random() * IDLE_SPAN);
  }

  // Any interaction resets the idle clock, and sends a visible mascot home.
  // A tap on the mascot himself is not "activity": it must reach his click
  // handler (giggle) instead of hiding him first. The idle re-arm is throttled
  // so a scroll (many events a second) doesn't churn timers.
  let lastArm = 0;
  function activity(e) {
    if (e.target.closest?.(".mascot")) return;
    if (up) hide();
    else {
      const t = Date.now();
      if (t - lastArm < 1000) return;
      lastArm = t;
      schedule();
    }
  }

  function init() {
    for (const ev of ["pointerdown", "keydown", "scroll", "touchstart"]) {
      root.addEventListener(ev, activity, { passive: true, capture: true });
    }
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) hide(); else schedule();
      syncMotion();
    });
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
    if (up) { tilt = gazeFromTilt(a.x, a.y, needsPermission()); applyGaze(); }
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
    shakeOn = true;
    if (needsPermission()) shakeMemo(true);
    syncMotion();
    return "granted";
  }
  // iOS forgets the motion grant on a full relaunch (a new version usually means
  // one). Remember the user turned shake on and re-request on their first tap in
  // the next session: requestPermission needs a gesture, and if iOS still holds
  // the grant this is silent.
  const SHAKE_KEY = "now.shakeOn";
  function shakeMemo(on) {
    try { on ? root.localStorage.setItem(SHAKE_KEY, "1") : root.localStorage.removeItem(SHAKE_KEY); } catch (_) { /* unavailable */ }
  }
  function armOnFirstTap(doc, storage, request) {
    let remembered = null;
    try { remembered = storage.getItem(SHAKE_KEY); } catch (_) { return false; }
    if (remembered !== "1") return false;
    doc.addEventListener("pointerup", async () => {
      const result = await request();
      if (result === "denied") shakeMemo(false); // don't prompt on every launch
      try { root.dispatchEvent(new root.CustomEvent("shake-rearm", { detail: result })); } catch (_) { /* no events here */ }
    }, { once: true, capture: true });
    return true;
  }
  // The motion stream is ~60 readings a second, so only listen while the shake
  // feature is armed, the page is visible and the mascot is enabled.
  // (Adding or removing the same listener twice is a no-op.)
  function syncMotion() {
    const want = shakeOn && enabled() && !document.hidden;
    root[want ? "addEventListener" : "removeEventListener"]("devicemotion", onMotion);
  }
  // Android and desktop need no permission: arm right away.
  if (typeof document !== "undefined" && shakeSupported() && !needsPermission()) requestShake();
  if (typeof document !== "undefined" && needsPermission()) armOnFirstTap(document, root.localStorage, requestShake);

  // A reaction to something that just happened. Polite by design: a global
  // 10s gap between reactions, a per-topic cooldown, and never while you're
  // busy (sheet/menu/typing), away, or while he's already up.
  const lastReact = {};
  let lastAny = 0;
  // force: for news the user asked to hear about (another device wrote). It skips
  // the polite limits above and interrupts a bubble that is already up, but still
  // keeps quiet when the page is hidden, the mascot is off or motion is reduced.
  function react(text, { key = text, cooldown = 60000, delay = 900, happy = true, force = false } = {}) {
    setTimeout(() => {
      if (!enabled() || reduced() || document.hidden) return;
      if (force) {
        if (up) hide();
      } else {
        if (up || quiet()) return;
        const now = Date.now();
        if (now - lastAny < 10000 || now - (lastReact[key] || 0) < cooldown) return;
      }
      lastAny = lastReact[key] = Date.now();
      show({ text, happy });
    }, delay);
  }

  root.Mascot = {
    react,
    gaze: { fromTilt: gazeFromTilt, max: GAZE_MAX },
    shake: { onPeak(fn) { peakListener = fn; }, supported: shakeSupported, needsPermission, request: requestShake, armOnFirstTap, active: () => shakeOn, _onMotion: onMotion },
    enabled,
    setEnabled(on) { write(on ? "1" : "0"); if (!on) hide(); else schedule(); syncMotion(); },
    peek: (opts) => show(opts),
    cheer: () => show({ cheer: true, text: "All done! Look at you ✨" }),
    hide,
    setMessageSource(fn) { source = fn; },
  };
  if (typeof document !== "undefined") init();
})(typeof window !== "undefined" ? window : globalThis);
