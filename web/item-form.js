// One form for making and editing an item. Title, type chip, then a group per field the
// chosen type has (app/types.json `fields`). Changing the type shows/hides groups at once;
// hidden groups keep their values, so switching back finds them as they were.
// Loaded after editors.js (sheet helpers), fields-ui.js, date-picker.js and types-ui.js;
// they are used at call time only, so the FIELD_GROUPS list also loads under `node --test`.
const ItemForm = (() => {
  // Every editable field a type may list, in the order the sheet shows them. A field named in
  // types.json that is missing here has no input yet (tests/item-form.test.js checks this).
  // The calendar_event fields from location on are sync-only: no input, shown by the viewer.
  const FIELD_GROUPS = ["content", "due_date", "priority", "calendar_url", "repeat", "color", "links", "blocked_by", "references", "attachments",
    "location", "end_date", "repeat_summary", "conference_url", "attendees", "notes"];
  // A new item only asks for what is needed to file it; the rest is one Edit away.
  // A note's body is the point of creating one, so it is asked for up front.
  const CREATE_FIELDS = ["due_date", "content"];

  // The type a new item under `parent` starts as: its newest sibling's, else the default.
  function defaultTypeFor(parent) {
    const siblings = parent ? parent.child_ids.map((id) => model.todosById.get(id)).filter(Boolean) : model.roots;
    return Types.defaultChildType(parent, siblings);
  }

  // opts: mode "edit" (todo) or "create" (parent: the todo the new item goes under).
  function render({ mode, todo, parent }) {
    const editing = mode === "edit";
    const titleInput = document.createElement("input");
    titleInput.type = "text";
    titleInput.placeholder = editing ? "Title" : "Item title";
    titleInput.enterKeyHint = "done";
    if (editing) titleInput.value = todo.title;

    const picker = DatePicker.create({
      value: editing && todo.due_date ? todo.due_date.slice(0, 10) : "",
      time: editing ? Due.timePart(todo.due_date) : "",
      withTime: true,
    });
    const repeatControls = editing ? renderRepeatControls(picker.dateInput, todo.repeat) : null;
    const extra = editing ? FieldsUI.renderEditFields(todo) : { groups: {}, changes: () => ({ fields: {} }) };
    const contentBox = document.createElement("textarea");
    contentBox.className = "note-content";
    contentBox.rows = 16;
    contentBox.placeholder = "Write…";
    if (editing && todo.content) contentBox.value = todo.content;
    let contentEditor = null;
    const contentValue = () => (contentEditor ? contentEditor.value() : contentBox.value).replace(/\s+$/, "");

    const priority = document.createElement("select");
    for (const [value, label] of [["high", "High"], ["normal", "Normal"], ["low", "Low"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      priority.append(option);
    }
    if (editing) priority.value = todo.priority || "normal";

    const contentLabel = DOM.el("p", "sheet-label", "Note");
    const nodes = {
      content: [contentLabel, contentBox],
      due_date: [DOM.label("Due date", picker.dateInput), picker.chips, picker.timeField],
      ...(editing ? { priority: [DOM.label("Priority", priority), priority] } : {}),
      ...(editing ? { repeat: [DOM.label("Repeat every", repeatControls.unit), repeatControls.row] } : {}),
      ...extra.groups,
      // Images upload as soon as they are added (online only), independent of Save.
      ...(editing ? { attachments: [AttachmentsUI.renderSection(todo)] } : {}),
    };
    const initialType = editing ? Types.nameOf(todo) : defaultTypeFor(parent);
    const groups = FIELD_GROUPS.filter((f) => nodes[f] && (editing || CREATE_FIELDS.includes(f))).map((field) => {
      const g = document.createElement("div");
      g.className = "field-group";
      g.dataset.field = field;
      g.append(...nodes[field]);
      return g;
    });
    const showFields = (type) => {
      for (const g of groups) g.hidden = !Types.hasField({ type }, g.dataset.field);
      // CodeMirror measures itself; a note field that was hidden comes out at height 0.
      if (Types.hasField({ type }, "content") && contentEditor) {
        requestAnimationFrame(() => contentEditor.refresh());
      }
    };
    const typePicker = TypeUI.create({ value: initialType, onChange: showFields });
    showFields(initialType);

    const submit = () => {
      const title = titleInput.value.trim();
      if (!title) return;
      const chosen = { type: typePicker.get() };
      const dated = Types.hasField(chosen, "due_date");
      if (!editing) {
        const body = Types.hasField(chosen, "content") ? contentValue() : "";
        reportedFailure(saveSplit(parent.todo_id, [title], dated ? picker.value() : null, chosen.type, body));
        return;
      }
      const result = extra.changes();
      if (result.error) {
        showNotice({ level: "error", message: result.error });
        return;
      }
      // Fields the type doesn't have are left exactly as stored.
      const fields = Object.fromEntries(Object.entries(result.fields).filter(([f]) => Types.hasField(chosen, f)));
      if (Types.hasField(chosen, "priority") && priority.value !== (todo.priority || "normal")) {
        fields.priority = priority.value;
      }
      if (Types.hasField(chosen, "content") && contentValue() !== (todo.content || "")) {
        fields.content = contentValue();
      }
      if (chosen.type !== Types.nameOf(todo)) fields.type = chosen.type;
      reportedFailure(saveEdit(todo.todo_id, title,
        dated ? picker.value() : undefined,
        dated ? repeatControls.value() : null, fields));
    };
    if (!editing) {
      titleInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          submit();
        }
      });
    }

    const body = DOM.el("div", "sheet-body");
    body.append(DOM.el("h2", "sheet-title", editing ? "Edit item" : "New item"));
    if (!editing) body.append(DOM.el("p", "sheet-subtitle", `In ${parent.title}`));
    body.append(DOM.label("Title", titleInput), titleInput, DOM.el("p", "sheet-label", "Type"),
      typePicker.node, ...groups);
    const screen = renderSheet(body, renderEditorActions(submit, editing ? "Save" : "Add"));
    screen.classList.add("sheet-full");
    requestAnimationFrame(() => {
      if (typeof MarkdownEditor !== "undefined") contentEditor = MarkdownEditor.attach(contentBox);
    });
    return screen;
  }

  return { render, defaultTypeFor, FIELD_GROUPS };
})();

if (typeof module === "object" && module.exports) module.exports = ItemForm;
