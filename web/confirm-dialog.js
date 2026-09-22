// The one blocking confirm popup: a message plus Yes/No. Dismissing it (Escape,
// tap outside, No) always counts as "no" and runs onCancel if given. DOM-only
// (like attachments-ui.js's lightbox), so this has no node --test coverage;
// exercise it in the browser.
const ConfirmDialog = (() => {
  const el = DOM.el;

  // opts: message, confirmLabel ("Yes"), cancelLabel ("No"), onConfirm(), onCancel().
  function open({ message, confirmLabel = "Yes", cancelLabel = "No", onConfirm, onCancel }) {
    const overlay = el("div", "confirm-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", message);
    const card = el("div", "confirm-card");
    const text = el("p", "confirm-message", message);
    const actions = el("div", "confirm-actions");

    const close = (run) => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      if (run) run();
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(onCancel); }
    };

    const cancelBtn = DOM.button(cancelLabel, "btn btn-plain", () => close(onCancel));
    const confirmBtn = DOM.button(confirmLabel, "btn btn-primary", () => close(onConfirm));
    actions.append(cancelBtn, confirmBtn);
    card.append(text, actions);
    overlay.append(card);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(onCancel); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    confirmBtn.focus();
  }

  return { open };
})();
