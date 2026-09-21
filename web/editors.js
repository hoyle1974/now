// The split and type sheets, the todo viewer, and the shared sheet helpers
// (the edit and new-item sheets are ItemForm, item-form.js).
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).
// Shared Cancel/Save row for the inline editors below — each editor supplies
// its own content elements and save behavior, but the button chrome and the
// "Cancel closes this panel" behavior are identical across all of them.
function renderEditorActions(onSave, saveLabel = "Save") {
  return DOM.actionBar(
    DOM.sheetButton("Cancel", "plain", () => {
      const back = viewerOrigin;
      setActivePanel(back ? "view" : null, back);
      renderTree();
    }),
    DOM.sheetButton(saveLabel, "primary", onSave)
  );
}

function renderSheet(...children) {
  const editor = DOM.el("div", "sheet");
  editor.append(...children);
  // Focus the first field once it's in the DOM, so opening an editor from
  // the menu goes straight to typing instead of needing a second tap.
  requestAnimationFrame(() => editor.querySelector("input, textarea")?.focus());
  return editor;
}

// Full-screen sheet: a heading and the fields scroll, the action bar stays put.
function renderFullSheet(title, nodes, buttons, subtitle) {
  const body = DOM.el("div", "sheet-body");
  body.append(DOM.el("h2", "sheet-title", title));
  if (subtitle) body.append(DOM.el("p", "sheet-subtitle", subtitle));
  body.append(...nodes);
  const screen = renderSheet(body, buttons);
  screen.classList.add("sheet-full");
  return screen;
}

function renderSplitEditor(todo) {
  const textarea = document.createElement("textarea");
  textarea.placeholder = "One item per line";
  textarea.rows = 3;

  const buttons = renderEditorActions(() => {
    const descriptions = textarea.value
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    if (descriptions.length === 0) return;
    reportedFailure(saveSplit(todo.todo_id, descriptions));
  }, "Split");

  textarea.rows = 8;
  return renderFullSheet("Add several", [textarea], buttons, todo.title);
}

// "Repeat every [2] [weeks]" next to the due date. Repeating needs a date to
// count from, so it is disabled (and cleared) while the date is empty.
function renderRepeatControls(dateInput, rule) {
  const row = document.createElement("div");
  row.className = "repeat-row";
  const every = document.createElement("input");
  every.type = "number";
  every.min = "1";
  every.max = "999";
  every.inputMode = "numeric";
  every.setAttribute("aria-label", "Repeat every");
  const unit = document.createElement("select");
  const units = [
    ["", "Never"], ["day", "days"], ["weekday", "weekdays (Mon\u2013Fri)"],
    ["week", "weeks"], ["month", "months"], ["year", "years"],
  ];
  for (const [value, text] of units) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    unit.appendChild(option);
  }
  unit.value = rule ? rule.unit : "";
  every.value = rule ? String(rule.every || 1) : "1";
  const sync = () => {
    // "every 1 day" reads better than "every 1 days".
    const one = (parseInt(every.value, 10) || 1) === 1;
    for (const option of unit.options) {
      const base = { day: "day", week: "week", month: "month", year: "year" }[option.value];
      if (base) option.textContent = one ? base : base + "s";
    }
    if (!dateInput.value) unit.value = "";
    unit.disabled = !dateInput.value;
    every.hidden = !unit.value || unit.value === "weekday";
  };
  dateInput.addEventListener("input", sync);
  unit.addEventListener("change", sync);
  every.addEventListener("input", sync);
  sync();
  row.append(every, unit);
  return {
    row,
    unit,
    value: () => {
      if (!unit.value) return null;
      const n = Math.max(1, Math.min(999, parseInt(every.value, 10) || 1));
      return { unit: unit.value, every: unit.value === "weekday" ? 1 : n };
    },
  };
}

// The row menu's Type entry: pick a type and it applies at once (with an Undo toast).
function renderTypePanel(todo) {
  const picker = TypeUI.create({
    value: Types.nameOf(todo),
    layout: "list",
    onChange: (name) => {
      setActivePanel(null);
      if (name !== Types.nameOf(todo)) reportedFailure(setType(todo.todo_id, name));
      else renderTree();
    },
  });
  const actions = DOM.actionBar(DOM.sheetButton("Cancel", "plain", () => {
    setActivePanel(null);
    renderTree();
  }));
  return renderSheet(DOM.el("p", "sheet-label", "Change type"), picker.node, actions);
}

// Full-screen read-only look at one todo; Edit hands off to the edit sheet.
// trashed ({ deleted_with, trashed_at, onClose, onRestore }): the item is in the trash, so it is
// shown as it was (no editing, no live links or images) with Undelete instead of Edit.
function renderViewer(todo, counts, trashed = null) {
  const add = (parent, tag, className, text) => {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    parent.appendChild(node);
    return node;
  };
  const close = trashed ? trashed.onClose : () => {
    setActivePanel(null);
    renderTree();
  };

  const body = document.createElement("div");
  body.className = "sheet-body";
  add(body, "h2", "sheet-title" + (todo.done && Types.can(todo, "hasCheckbox") ? " is-done" : ""), todo.title);

  const facts = document.createElement("dl");
  facts.className = "view-facts";
  const fact = (name, value) => {
    add(facts, "dt", "sheet-label", name);
    add(facts, "dd", "view-value", value);
  };
  fact("Type", Types.get(todo).label);
  if (Types.can(todo, "hasCheckbox")) fact("Status", todo.done ? "Done" : "Open");
  if (Types.hasField(todo, "due_date")) fact("Due", todo.due_date ? Due.format(todo.due_date) : "No due date");
  if (todo.repeat && Types.hasField(todo, "repeat")) fact("Repeats", Due.formatRepeat(todo.repeat));
  if (counts && counts.total && Types.can(todo, "showsProgress")) fact("Subtasks", `${counts.done} of ${counts.total} done`);
  if (!trashed && Fields.isBlocked(todo, model.todosById)) fact("Blocked", "Waiting on an unfinished todo");
  if (trashed) {
    fact("Deleted", new Date(trashed.trashed_at).toLocaleString(undefined,
      { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }));
    if (trashed.deleted_with) fact("Deleted with", trashed.deleted_with);
  }
  body.appendChild(facts);
  body.appendChild(FieldsUI.renderDetail(todo, { trashed: Boolean(trashed) }));

  const buttons = DOM.actionBar(
    DOM.sheetButton("Close", "plain", close),
    trashed ? DOM.sheetButton("Undelete", "primary", trashed.onRestore)
      : DOM.sheetButton("Edit", "primary", () => {
        setActivePanel("edit", todo.todo_id);
        viewerOrigin = todo.todo_id;
        renderTree();
      })
  );

  const screen = renderSheet(body, buttons);
  screen.classList.add("sheet-full");
  return screen;
}

function renderEmptyState(heading = "All clear", message = "Add your first todo below.") {
  const badge = DOM.el("div", "todo-empty-icon");
  badge.appendChild(icon("check"));
  const empty = DOM.el("li", "todo-empty");
  empty.append(badge, DOM.el("p", "todo-empty-title", heading), DOM.el("p", "todo-empty-text", message));
  return empty;
}

