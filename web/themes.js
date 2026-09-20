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

  const pop = () => play([[784, 0, 0.18], [1175, 0.07, 0.24]]);
  const fanfare = () => play([[523, 0, 0.2], [659, 0.09, 0.2], [784, 0.18, 0.2], [1047, 0.27, 0.45]]);

  root.Themes = { THEMES, current, set, apply };
  root.Sound = { on: soundOn, set: setSound, pop, fanfare };
  if (root.document) apply();
})(typeof window !== "undefined" ? window : globalThis);
