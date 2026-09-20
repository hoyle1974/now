// Delight: a confetti burst when a todo is completed, and a bigger one when the
// last open todo is done. Pure decoration: skipped for reduced-motion, never
// blocks taps (pointer-events: none), and every piece removes itself.
(function (root) {
  const COLORS = ["#5856d6", "#ff9500", "#34c759", "#ff2d55", "#5ac8fa", "#ffcc00"];
  const reduced = () =>
    root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function piece(x, y, spread, lift) {
    const el = document.createElement("i");
    el.className = "confetti";
    const size = 5 + Math.random() * 6;
    el.style.cssText =
      `left:${x}px;top:${y}px;width:${size}px;height:${size * (Math.random() < 0.5 ? 1 : 0.5)}px;` +
      `background:${COLORS[Math.floor(Math.random() * COLORS.length)]};` +
      `border-radius:${Math.random() < 0.4 ? "50%" : "2px"}`;
    document.body.appendChild(el);
    const angle = Math.random() * Math.PI * 2;
    const dist = spread * (0.4 + Math.random() * 0.6);
    const dx = Math.cos(angle) * dist;
    const dy = Math.sin(angle) * dist - lift;
    const fall = 60 + Math.random() * 90;
    const spin = (Math.random() - 0.5) * 900;
    const anim = el.animate(
      [
        { transform: "translate(0,0) rotate(0deg) scale(0.4)", opacity: 1 },
        { transform: `translate(${dx}px,${dy}px) rotate(${spin / 2}deg) scale(1)`, opacity: 1, offset: 0.55 },
        { transform: `translate(${dx * 1.15}px,${dy + fall}px) rotate(${spin}deg) scale(0.8)`, opacity: 0 },
      ],
      { duration: 1000 + Math.random() * 600, easing: "cubic-bezier(.2,.7,.3,1)" }
    );
    anim.onfinish = () => el.remove();
  }

  // Small pop from a point (a checkbox).
  function burst(x, y, count = 14) {
    if (reduced() || typeof document === "undefined") return;
    for (let i = 0; i < count; i++) piece(x, y, 70, 20);
  }

  // Big celebration across the top of the screen.
  function celebrateAll() {
    if (reduced() || typeof document === "undefined") return;
    const w = root.innerWidth || 400;
    for (let i = 0; i < 46; i++) piece(w * (0.1 + Math.random() * 0.8), (root.innerHeight || 600) * 0.5, 130, 30);
    if (root.navigator && root.navigator.vibrate) root.navigator.vibrate([10, 40, 10, 40, 20]);
  }

  root.Sparkle = { burst, celebrateAll };
})(typeof window !== "undefined" ? window : globalThis);
