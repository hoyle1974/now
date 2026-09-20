// Accent themes and the optional completion sound. Both are per-device
// preferences kept in localStorage; if storage is unavailable the defaults hold.
(function (root) {
  const THEMES = {
    indigo: { name: "Indigo", light: ["#5856d6", "#4644b8"], dark: ["#7d7aff", "#6a67f0"] },
    ocean: { name: "Ocean", light: ["#007aff", "#0062cc"], dark: ["#4da3ff", "#2f8cf0"] },
    berry: { name: "Berry", light: ["#d6338a", "#b02671"], dark: ["#ff5fae", "#ee4a9b"] },
    forest: { name: "Forest", light: ["#248a53", "#1c6e42"], dark: ["#4cd48a", "#35bd73"] },
    sunset: { name: "Sunset", light: ["#e8590c", "#c24a09"], dark: ["#ff9a52", "#f0863a"] },
  };
  const THEME_KEY = "now.theme";
  const SOUND_KEY = "now.sound";

  const read = (key) => {
    try { return root.localStorage.getItem(key); } catch (_) { return null; }
  };
  const write = (key, value) => {
    try { root.localStorage.setItem(key, value); } catch (_) { /* unavailable */ }
  };
  const dark = () => root.matchMedia && root.matchMedia("(prefers-color-scheme: dark)").matches;

  function current() {
    const saved = read(THEME_KEY);
    return THEMES[saved] ? saved : "indigo";
  }

  function apply(id = current()) {
    const style = root.document.documentElement.style;
    if (id === "indigo") {
      style.removeProperty("--accent");
      style.removeProperty("--accent-pressed");
      return;
    }
    const [accent, pressed] = THEMES[id][dark() ? "dark" : "light"];
    style.setProperty("--accent", accent);
    style.setProperty("--accent-pressed", pressed);
  }

  function set(id) {
    if (!THEMES[id]) return;
    write(THEME_KEY, id);
    apply(id);
  }

  // ---- sound: a soft two-note chime, synthesized (no audio files) ----
  let ctx = null;
  const soundOn = () => read(SOUND_KEY) === "1";
  function setSound(on) { write(SOUND_KEY, on ? "1" : "0"); }

  function tone(freq, start, length, gain = 0.08) {
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    amp.gain.setValueAtTime(0, ctx.currentTime + start);
    amp.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.015);
    amp.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + length);
    osc.connect(amp).connect(ctx.destination);
    osc.start(ctx.currentTime + start);
    osc.stop(ctx.currentTime + start + length + 0.05);
  }

  function play(notes) {
    if (!soundOn()) return;
    try {
      const AC = root.AudioContext || root.webkitAudioContext;
      if (!AC) return;
      ctx = ctx || new AC();
      if (ctx.state === "suspended") ctx.resume();
      notes.forEach(([f, s, l]) => tone(f, s, l));
    } catch (_) { /* audio is decoration; never break a tap */ }
  }

  // Frequency sweep: the building block of chirps and boops.
  function sweep(f0, f1, start, length, type = "sine", gain = 0.07) {
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    const t0 = ctx.currentTime + start;
    osc.type = type;
    osc.frequency.setValueAtTime(f0, t0);
    osc.frequency.exponentialRampToValueAtTime(f1, t0 + length);
    amp.gain.setValueAtTime(0, t0);
    amp.gain.linearRampToValueAtTime(gain, t0 + 0.012);
    amp.gain.exponentialRampToValueAtTime(0.0001, t0 + length);
    osc.connect(amp).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + length + 0.05);
  }

  // The mascot's voice: chirps, boops and robot beeps (only when sound is on).
  const SFX = {
    peek: () => { sweep(500, 1500, 0, 0.13, "triangle"); sweep(900, 2000, 0.16, 0.11, "triangle"); },
    beep: () => { sweep(880, 880, 0, 0.09, "square", 0.03); sweep(660, 660, 0.12, 0.09, "square", 0.03); sweep(990, 990, 0.24, 0.14, "square", 0.03); },
    // The idle pop-up is meant to be barely there: pure sines at a whisper.
    peekSoft: () => { sweep(520, 980, 0, 0.14, "sine", 0.008); sweep(760, 1250, 0.17, 0.12, "sine", 0.006); },
    beepSoft: () => { sweep(700, 700, 0, 0.1, "sine", 0.005); sweep(880, 880, 0.13, 0.12, "sine", 0.005); },
    blinkSoft: () => sweep(1900, 1600, 0, 0.04, "sine", 0.004),
    hideSoft: () => sweep(700, 300, 0, 0.18, "sine", 0.006),
    blink: () => sweep(2200, 1800, 0, 0.04, "sine", 0.04),
    hide: () => { sweep(900, 260, 0, 0.2, "triangle"); },
    giggle: () => { [0, 0.11, 0.22].forEach((s, i) => sweep(900 + i * 220, 1500 + i * 260, s, 0.09, "triangle")); },
    cheer: () => {
      sweep(600, 1800, 0, 0.16, "triangle");
      [880, 1109, 1319, 1760].forEach((f, i) => sweep(f, f * 1.02, 0.2 + i * 0.09, 0.14, "triangle"));
      sweep(1200, 2400, 0.62, 0.12, "triangle");
    },
  };
  function sfx(name) {
    if (!SFX[name]) return;
    play([]); // sets up / resumes the audio context (no-op when sound is off)
    if (ctx && soundOn()) { try { SFX[name](); } catch (_) { /* decoration */ } }
  }

  // iOS keeps audio locked until a tap: unlock on any touch so the mascot's
  // self-started chirps can play later.
  function unlock() {
    if (!soundOn()) return;
    try {
      const AC = root.AudioContext || root.webkitAudioContext;
      if (!AC) return;
      ctx = ctx || new AC();
      if (ctx.state === "suspended") ctx.resume();
    } catch (_) { /* ignore */ }
  }
  if (root.addEventListener) root.addEventListener("pointerdown", unlock, { capture: true, passive: true });

  const pop = () => play([[784, 0, 0.18], [1175, 0.07, 0.24]]);
  const fanfare = () => play([[523, 0, 0.2], [659, 0.09, 0.2], [784, 0.18, 0.2], [1047, 0.27, 0.45]]);

  root.Themes = { THEMES, current, set, apply };
  root.Sound = { on: soundOn, set: setSound, pop, fanfare, sfx };
  if (root.document) apply();
})(typeof window !== "undefined" ? window : globalThis);
