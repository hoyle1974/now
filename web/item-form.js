// One form for making and editing an item. Title, type chip, then a group per field the
// chosen type has (app/types.json `fields`). Changing the type shows/hides groups at once;
// hidden groups keep their values, so switching back finds them as they were.
// Loaded after editors.js (sheet helpers), fields-ui.js, date-picker.js and types-ui.js;
// they are used at call time only, so the FIELD_GROUPS list also loads under `node --test`.
const ItemForm = (() => {
  // Every editable field a type may list, in the order the sheet shows them. A field named in
  // types.json that is missing here has no input yet (tests/item-form.test.js checks this).
  const FIELD_GROUPS = ["due_date", "repeat", "color", "links", "blocked_by", "references"];
  // A new item only asks for what is needed to file it; the rest is one Edit away.
  const CREATE_FIELDS = ["due_date"];

  function labelFor(text, forEl) {
    const label = document.createElement("label");
    label.className = "sheet-label";
    label.textContent = text;
    forEl.id = `field-${Math.random().toString(36).slice(2)}`;
    label.htmlFor = forEl.id;
    return label;
  }

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

    const nodes = {
      due_date: [labelFor("Due date", picker.dateInput), picker.chips, picker.timeField],
      ...(editing ? { repeat: [labelFor("Repeat every", repeatControls.unit), repeatControls.row] } : {}),
      ...extra.groups,
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
    };
    const typePicker = TypeUI.create({ value: initialType, onChange: showFields });
    showFields(initialType);

    const submit = () => {
      const title = titleInput.value.trim();
      if (!title) return;
      const chosen = { type: typePicker.get() };
      const dated = Types.hasField(chosen, "due_date");
      if (!editing) {
        reportedFailure(saveSplit(parent.todo_id, [title], dated ? picker.value() : null, chosen.type));
        return;
      }
      const result = extra.changes();
      if (result.error) {
        showNotice({ level: "error", message: result.error });
        return;
      }
      // Fields the type doesn't have are left exactly as stored.
      const fields = Object.fromEntries(Object.entries(result.fields).filter(([f]) => Types.hasField(chosen, f)));
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

    const heading = document.createElement("h2");
    heading.className = "sheet-title";
    heading.textContent = editing ? "Edit item" : "New item";
    const body = document.createElement("div");
    body.className = "sheet-body";
    body.append(heading);
    if (!editing) {
      const sub = document.createElement("p");
      sub.className = "sheet-subtitle";
      sub.textContent = `In ${parent.title}`;
      body.append(sub);
    }
    const typeLabel = document.createElement("p");
    typeLabel.className = "sheet-label";
    typeLabel.textContent = "Type";
    body.append(labelFor("Title", titleInput), titleInput, typeLabel, typePicker.node, ...groups);
    const screen = renderSheet(body, renderEditorActions(submit, editing ? "Save" : "Add"));
    screen.classList.add("sheet-full");
    return screen;
  }

  return { render, defaultTypeFor, FIELD_GROUPS };
})();

if (typeof module === "object" && module.exports) module.exports = ItemForm;
