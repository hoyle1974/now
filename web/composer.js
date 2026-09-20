// The add-todo composer and its due-date chips.
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).

// ---- Composer: due date chips -----------------------------------------------
// A calendar button opens a row of Today / Tomorrow / Pick date. #add-due (the
// native date input inside the "Pick date" chip) holds the chosen value.

const addForm = document.getElementById("add-form");
const addChips = document.getElementById("add-chips");
const addDueToggle = document.getElementById("add-due-toggle");
const addDue = document.getElementById("add-due");
const addPickText = document.getElementById("add-pick-text");

function renderComposerDue() {
  const value = addDue.value;
  const isToday = value === getTodayString();
  const isTomorrow = value === getTomorrowString();
  addChips.querySelector('[data-due="today"]').classList.toggle("is-active", isToday);
  addChips.querySelector('[data-due="tomorrow"]').classList.toggle("is-active", isTomorrow);
  const custom = !!value && !isToday && !isTomorrow;
  document.getElementById("add-pick").classList.toggle("is-active", custom);
  addPickText.textContent = custom ? formatDue(`${value}T00:00:00`) : "Pick date";
  addDueToggle.classList.toggle("has-value", !!value);
  addDueToggle.setAttribute("aria-label", value ? `Due ${value}. Change due date` : "Set due date");
}

function setComposerChips(open) {
  addChips.hidden = !open;
  addDueToggle.setAttribute("aria-expanded", String(open));
}

addDueToggle.addEventListener("click", () => setComposerChips(addChips.hidden));

addChips.addEventListener("click", (event) => {
  const chip = event.target.closest("[data-due]");
  if (!chip) return;
  const value = chip.dataset.due === "today" ? getTodayString() : getTomorrowString();
  addDue.value = addDue.value === value ? "" : value; // tapping the chosen chip clears it
  renderComposerDue();
});

// The date input sits invisibly over its chip; some desktop browsers only open
// the picker from a small icon, so ask for it explicitly.
document.getElementById("add-pick").addEventListener("click", () => {
  try { addDue.showPicker(); } catch (e) { /* unsupported: the input still works */ }
});
addDue.addEventListener("input", renderComposerDue);

// Tell the CSS how tall the composer is, so padding and popups clear it.
// Measured from the rendered box (incl. the home-indicator padding), and
// re-measured on viewport changes, since iOS resizes the visual viewport when
// the toolbar or keyboard moves.
function measureComposer() {
  const h = Math.ceil(Math.max(addForm.offsetHeight, addForm.getBoundingClientRect().height));
  document.documentElement.style.setProperty("--composer-h", `${h}px`);
}
new ResizeObserver(measureComposer).observe(addForm);
window.addEventListener("resize", measureComposer);
window.addEventListener("orientationchange", measureComposer);
if (window.visualViewport) window.visualViewport.addEventListener("resize", measureComposer);
window.addEventListener("load", measureComposer);
measureComposer();

let createdThisSession = 0;
addForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("add-title");
  const title = input.value.trim();
  if (!title) return;
  const payload = { title };
  if (addDue.value) {
    payload.due_date = addDue.value;
  }
  engine.enqueue({ kind: "create", payload });
  if (window.Mascot) {
    createdThisSession += 1;
    if (createdThisSession === 1 || createdThisSession % 5 === 0) {
      window.Mascot.react(["Added!", "On the list.", "Got it.", "Noted!"][createdThisSession % 4], { key: "added", cooldown: 45000, delay: 700 });
    }
  }
  input.value = "";
  addDue.value = "";
  renderComposerDue();
  setComposerChips(false);
});
