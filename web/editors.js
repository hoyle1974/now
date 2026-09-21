// The split and type sheets, the todo viewer, and the shared sheet helpers
// (the edit and new-item sheets are ItemForm, item-form.js).
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).
// Shared Cancel/Save row for the inline editors below — each editor supplies
// its own content elements and save behavior, but the button chrome and the
// "Cancel closes this panel" behavior are identical across all of them.
function renderEditorActions(onSave, saveLabel = "Save") {
  const buttons = document.createElement("div");
  buttons.className = "sheet-actions";

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "btn btn-plain";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => {
    const back = viewerOrigin;
    setActivePanel(back ? "view" : null, back);
    renderTree();
  });

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "btn btn-primary";
  saveBtn.textContent = saveLabel;
  saveBtn.addEventListener("click", onSave);

  buttons.append(cancelBtn, saveBtn);
  return buttons;
}

function renderSheet(...children) {
  const editor = document.createElement("div");
  editor.className = "sheet";
  editor.append(...children);
  // Focus the first field once it's in the DOM, so opening an editor from
  // the menu goes straight to typing instead of needing a second tap.
  requestAnimationFrame(() => editor.querySelector("input, textarea")?.focus());
  return editor;
}

// Full-screen sheet: a heading and the fields scroll, the action bar stays put.
function renderFullSheet(title, nodes, buttons, subtitle) {
  const heading = document.createElement("h2");
  heading.className = "sheet-title";
  heading.textContent = title;
  const body = document.createElement("div");
  body.className = "sheet-body";
  body.append(heading);
  if (subtitle) {
    const sub = document.createElement("p");
    sub.className = "sheet-subtitle";
    sub.textContent = subtitle;
    body.append(sub);
  }
  body.append(...nodes);
  const screen = renderSheet(body, buttons);
  screen.classList.add("sheet-full");
  return screen;
}

function sheetLabel(text, forEl) {
  const label = document.createElement("label");
  label.className = "sheet-label";
  label.textContent = text;
  forEl.id = `field-${Math.random().toString(36).slice(2)}`;
  label.htmlFor = forEl.id;
  return label;
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
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "btn btn-plain";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => {
    setActivePanel(null);
    renderTree();
  });
  const actions = document.createElement("div");
  actions.className = "sheet-actions";
  actions.appendChild(cancel);
  const heading = document.createElement("p");
  heading.className = "sheet-label";
  heading.textContent = "Change type";
  return renderSheet(heading, picker.node, actions);
}

// Full-screen read-only look at one todo; Edit hands off to the edit sheet.
function renderViewer(todo, counts) {
  const add = (parent, tag, className, text) => {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    parent.appendChild(node);
    return node;
  };
  const close = () => {
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
  if (Types.hasField(todo, "due_date")) fact("Due", todo.due_date ? formatDue(todo.due_date) : "No due date");
  if (todo.repeat && Types.hasField(todo, "repeat")) fact("Repeats", Due.formatRepeat(todo.repeat));
  if (counts && counts.total && Types.can(todo, "showsProgress")) fact("Subtasks", `${counts.done} of ${counts.total} done`);
  if (Fields.isBlocked(todo, model.todosById)) fact("Blocked", "Waiting on an unfinished todo");
  body.appendChild(facts);
  body.appendChild(FieldsUI.renderDetail(todo));

  const buttons = document.createElement("div");
  buttons.className = "sheet-actions";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "btn btn-plain";
  closeBtn.textContent = "Close";
  closeBtn.addEventListener("click", close);
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "btn btn-primary";
  editBtn.textContent = "Edit";
  editBtn.addEventListener("click", () => {
    setActivePanel("edit", todo.todo_id);
    viewerOrigin = todo.todo_id;
    renderTree();
  });
  buttons.append(closeBtn, editBtn);

  const screen = renderSheet(body, buttons);
  screen.classList.add("sheet-full");
  return screen;
}

function renderEmptyState(heading = "All clear", message = "Add your first todo below.") {
  const empty = document.createElement("li");
  empty.className = "todo-empty";
  const badge = document.createElement("div");
  badge.className = "todo-empty-icon";
  badge.appendChild(icon("check"));
  const title = document.createElement("p");
  title.className = "todo-empty-title";
  title.textContent = heading;
  const text = document.createElement("p");
  text.className = "todo-empty-text";
  text.textContent = message;
  empty.append(badge, title, text);
  return empty;
}

