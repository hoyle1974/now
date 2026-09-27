// The one type control, built from the registry: a chip row while there are few types,
// a dropdown when there are many. Pass layout "list" for the described list (the row
// menu's Type panel, where each type's description fits). Used by the edit and new-item
// sheets, that panel and the composer, so adding a type to app/types.json adds it
// everywhere. Depends on Types (types.js) and icon() (ui-helpers.js) at call time.
const TypeUI = (() => {
  const ROW_MAX = 4; // up to this many types show as a chip row; more become a dropdown

  // "a Project", "an Event"
  function withArticle(label) {
    return (/^[aeiou]/i.test(label) ? "an " : "a ") + label;
  }

  const labelOf = (name) => Types.get({ type: name }).label;

  // A chip-shaped face for a type: its icon and label.
  function face(name, className) {
    const node = document.createElement("span");
    node.className = className || "type-face";
    node.append(icon(Types.get({ type: name }).icon), document.createTextNode(labelOf(name)));
    return node;
  }

  // A closed dropdown. The select itself is the value snapshotSheet/restoreSheet carries.
  function createSelect(value, onChange) {
    const node = document.createElement("div");
    node.className = "type-select";
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Type");
    for (const name of Types.userNames) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = labelOf(name);
      select.append(option);
    }
    select.value = Types.nameOf({ type: value });
    let shown = select.value;
    const emit = () => {
      if (select.value === shown) return;
      shown = select.value;
      if (onChange) onChange(select.value);
    };
    // input covers restoreSheet; change covers browsers that skip input on a select.
    select.addEventListener("input", emit);
    select.addEventListener("change", emit);
    node.append(select);
    return {
      node,
      get: () => select.value,
      // Silent: opening the picker must not count as a choice.
      set: (name) => { select.value = name; shown = name; },
    };
  }

  // opts: value (type name), onChange(name), layout ("row" | "list" | "select", default by count).
  // The chosen type also lives in a hidden input inside the node, so an open sheet keeps it
  // across the re-render that snapshotSheet/restoreSheet (tree-view.js) carries fields over.
  function create({ value, onChange, layout } = {}) {
    const mode = layout || (Types.userNames.length <= ROW_MAX ? "row" : "select");
    if (mode === "select") return createSelect(value, onChange);
    const node = document.createElement("div");
    node.className = mode === "row" ? "chip-row type-picker" : "type-list";
    node.setAttribute("role", "radiogroup");
    node.setAttribute("aria-label", "Type");
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.value = Types.nameOf({ type: value });
    const buttons = new Map();
    for (const name of Types.userNames) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "radio");
      if (mode === "row") {
        btn.className = "chip type-chip";
        btn.append(icon(Types.get({ type: name }).icon), document.createTextNode(labelOf(name)));
      } else {
        btn.className = "type-option";
        const text = document.createElement("span");
        text.className = "type-option-text";
        const title = document.createElement("span");
        title.className = "type-option-label";
        title.textContent = labelOf(name);
        const desc = document.createElement("span");
        desc.className = "type-option-desc";
        desc.textContent = Types.get({ type: name }).description;
        text.append(title, desc);
        btn.append(icon(Types.get({ type: name }).icon), text);
      }
      btn.addEventListener("click", () => {
        hidden.value = name;
        hidden.dispatchEvent(new Event("input"));
      });
      buttons.set(name, btn);
      node.appendChild(btn);
    }
    node.appendChild(hidden);
    const render = () => {
      for (const [name, btn] of buttons) {
        const on = name === hidden.value;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-checked", String(on));
      }
    };
    hidden.addEventListener("input", () => {
      render();
      if (onChange) onChange(hidden.value);
    });
    render();
    return { node, get: () => hidden.value, set: (name) => { hidden.value = name; hidden.dispatchEvent(new Event("input")); } };
  }

  return { create, face, labelOf, withArticle };
})();
