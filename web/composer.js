// The add-todo composer and its due-date chips.
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).

// ---- Composer: due date and type ---------------------------------------------
// The shared DatePicker's chips sit above the bar, opened by the calendar button. The type
// chip shows what the next item will be: the type of the newest top-level item, unless
// changed here for one item.

const addForm = document.getElementById("add-form");
const addDueToggle = document.getElementById("add-due-toggle");
const addType = document.getElementById("add-type");

const composerDate = DatePicker.create({ rowClass: "composer-chips", onChange: () => renderComposerDue() });
composerDate.chips.hidden = true;
addForm.prepend(composerDate.chips);

function renderComposerDue() {
  const value = composerDate.date();
  addDueToggle.classList.toggle("has-value", !!value);
  addDueToggle.setAttribute("aria-label", value ? `Due ${value}. Change due date` : "Set due date");
}

function setComposerChips(open) {
  composerDate.chips.hidden = !open;
  addDueToggle.setAttribute("aria-expanded", String(open));
}

addDueToggle.addEventListener("click", () => setComposerChips(composerDate.chips.hidden));

let composerTypeChoice = null; // set by the picker for the next item only
const composerType = () => composerTypeChoice || ItemForm.defaultTypeFor(null);

let typePop = null;
function closeTypePop() {
  if (typePop) typePop.remove();
  typePop = null;
  addType.setAttribute("aria-expanded", "false");
}

function renderComposerType() {
  const type = composerType();
  addType.replaceChildren(icon(Types.get({ type }).icon));
  addType.setAttribute("aria-label", `Type: ${TypeUI.labelOf(type)}. Change type`);
  // A type without a due date has nothing to set one on.
  const dated = Types.hasField({ type }, "due_date");
  addDueToggle.hidden = !dated;
  if (!dated) setComposerChips(false);
}

addType.addEventListener("click", () => {
  if (typePop) { closeTypePop(); return; }
  const picker = TypeUI.create({
    value: composerType(),
    layout: "list",
    onChange: (name) => {
      composerTypeChoice = name;
      closeTypePop();
      renderComposerType();
    },
  });
  typePop = document.createElement("div");
  typePop.className = "type-pop";
  typePop.appendChild(picker.node);
  addForm.appendChild(typePop);
  addType.setAttribute("aria-expanded", "true");
});
document.addEventListener("click", (event) => {
  if (typePop && !event.target.closest(".type-pop, #add-type")) closeTypePop();
});

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
  // A new top-level todo gets a random color; the server stores the one we send.
  const type = composerType();
  const payload = { title, type, color: Fields.COLORS[Math.floor(Math.random() * Fields.COLORS.length)] };
  if (composerDate.date() && Types.hasField({ type }, "due_date")) {
    payload.due_date = composerDate.date();
  }
  engine.enqueue({ kind: "create", payload });
  if (window.Mascot) {
    createdThisSession += 1;
    if (createdThisSession === 1 || createdThisSession % 5 === 0) {
      window.Mascot.react(["Added!", "On the list.", "Got it.", "Noted!"][createdThisSession % 4], { key: "added", cooldown: 45000, delay: 700 });
    }
  }
  input.value = "";
  composerDate.set("");
  setComposerChips(false);
  composerTypeChoice = null;
});
renderComposerType();
