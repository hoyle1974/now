// Small DOM builders shared by every UI script, so no file redefines its own.
// Loaded before the scripts that use them; nothing here touches the page at load time.
const DOM = (() => {
  // el("div", "class names", "text"): className and text are optional.
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  // A type="button" button (so it never submits a surrounding form).
  function button(text, className, onClick) {
    const node = el("button", className, text);
    node.type = "button";
    if (onClick) node.addEventListener("click", onClick);
    return node;
  }

  // The Cancel/Save-style row at the bottom of a sheet. kind: "plain" | "primary".
  function sheetButton(text, kind, onClick) {
    return button(text, `btn btn-${kind}`, onClick);
  }

  function actionBar(...buttons) {
    const bar = el("div", "sheet-actions");
    bar.append(...buttons);
    return bar;
  }

  // A sheet label wired to its input, so tapping the label focuses the field.
  function label(text, forEl) {
    const node = el("label", "sheet-label", text);
    forEl.id = `field-${Math.random().toString(36).slice(2)}`;
    node.htmlFor = forEl.id;
    return node;
  }

  return { el, button, sheetButton, actionBar, label };
})();
