// DOM for the color / links / blocked-by / references fields: the row accent,
// the "Blocked" chip, the folded detail panel and the edit-sheet controls.
// Depends on Fields (fields.js); app.js hands it the model and focusTodo.
const FieldsUI = (() => {
  let deps = { model: null, focusTodo: () => {} };

  function init(d) { deps = d; }

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };

  // ---- row decoration -------------------------------------------------------

  function decorateRow(row, todo) {
    const color = Fields.effectiveColor(todo, deps.model.todosById);
    if (color) row.dataset.color = color;
  }

  function blockedChip(todo) {
    if (!Fields.isBlocked(todo, deps.model.todosById)) return null;
    const chip = el("span", "todo-chip todo-chip--blocked", "Blocked");
    chip.setAttribute("aria-label", "Blocked by an unfinished todo");
    return chip;
  }

  // ---- detail panel ---------------------------------------------------------

  // Taps on real controls inside the row must not fold/unfold it.
  function isRowTap(target) {
    return !target.closest("input, label, button, a, textarea, .todo-menu, .todo-drag-handle");
  }

  function todoButton(todo, tapClass) {
    const btn = el("button", `detail-item ${tapClass || ""}`.trim(), todo.title);
    btn.type = "button";
    if (todo.done) btn.classList.add("is-done");
    btn.addEventListener("click", (e) => deps.focusTodo(todo.todo_id, e.clientY));
    return btn;
  }

  function renderDetail(todo) {
    const { todosById } = deps.model;
    const panel = el("div", "todo-detail");
    let any = false;

    const links = (todo.links || []).filter((l) => Fields.isSafeUrl(l.url));
    if (links.length) {
      any = true;
      panel.appendChild(el("p", "detail-heading", "Links"));
      for (const link of links) {
        const a = el("a", "detail-item detail-link", link.label || link.url);
        a.href = link.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        panel.appendChild(a);
      }
    }
    const blockers = Fields.resolveRefs(todo.blocked_by, todosById).filter((t) => !t.deleted);
    if (blockers.length) {
      any = true;
      panel.appendChild(el("p", "detail-heading", "Blocked by"));
      blockers.forEach((t) => panel.appendChild(todoButton(t)));
    }
    const refs = Fields.resolveRefs(todo.references, todosById).filter((t) => !t.deleted);
    if (refs.length) {
      any = true;
      panel.appendChild(el("p", "detail-heading", "References"));
      refs.forEach((t) => panel.appendChild(todoButton(t)));
    }
    if (!any) panel.appendChild(el("p", "detail-empty", "No links or related todos. Add them from Edit."));
    panel.appendChild(AttachmentsUI.renderSection(todo));
    return panel;
  }

  // ---- edit sheet controls --------------------------------------------------

  function label(text) { return el("p", "sheet-label", text); }

  function renderColorPicker(state) {
    const row = el("div", "swatch-row");
    row.setAttribute("role", "radiogroup");
    row.setAttribute("aria-label", "Color");
    const buttons = [];
    const paint = () => buttons.forEach(({ btn, value }) => {
      const on = state.color === value;
      btn.setAttribute("aria-checked", String(on));
      btn.classList.toggle("is-active", on);
    });
    const add = (value, name) => {
      const btn = el("button", "swatch" + (value ? "" : " swatch-none"));
      btn.type = "button";
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-label", name);
      if (value) btn.dataset.color = value;
      else btn.textContent = "×";
      btn.addEventListener("click", () => { state.color = value; paint(); });
      buttons.push({ btn, value });
      row.appendChild(btn);
    };
    add(null, "No color");
    Fields.COLORS.forEach((c) => add(c, c));
    paint();
    return row;
  }

  function renderLinksEditor(state) {
    const wrap = el("div", "links-editor");
    const rows = el("div", "links-rows");
    const draw = () => {
      rows.replaceChildren();
      state.links.forEach((link, i) => {
        const item = el("div", "link-row");
        const url = el("input");
        url.type = "text";
        url.inputMode = "url";
        url.placeholder = "https://";
        url.value = link.url;
        url.setAttribute("aria-label", "Link URL");
        url.autocapitalize = "off";
        url.addEventListener("input", () => { link.url = url.value; });
        const lab = el("input");
        lab.type = "text";
        lab.placeholder = "Label (optional)";
        lab.value = link.label || "";
        lab.setAttribute("aria-label", "Link label");
        lab.addEventListener("input", () => { link.label = lab.value; });
        const rm = el("button", "btn btn-plain link-remove", "Remove");
        rm.type = "button";
        rm.setAttribute("aria-label", "Remove link");
        rm.addEventListener("click", () => { state.links.splice(i, 1); draw(); });
        item.append(url, lab, rm);
        rows.appendChild(item);
      });
    };
    const add = el("button", "btn btn-plain link-add", "Add link");
    add.type = "button";
    add.addEventListener("click", () => {
      if (state.links.length >= Fields.MAX_LINKS) return;
      state.links.push({ url: "", label: "" });
      draw();
      rows.querySelector(".link-row:last-child input")?.focus();
    });
    draw();
    wrap.append(rows, add);
    return wrap;
  }

  // Searchable multi-select of the other todos.
  function renderTodoPicker(todo, ids, exclude = new Set()) {
    const { todosById } = deps.model;
    const wrap = el("div", "todo-picker");
    const chosen = el("div", "picker-chosen");
    const search = el("input");
    search.type = "text";
    search.placeholder = "Search todos";
    search.setAttribute("aria-label", "Search todos");
    search.autocomplete = "off";
    const list = el("div", "picker-list");

    const toggle = (id) => {
      if (ids.has(id)) ids.delete(id);
      else ids.add(id);
      draw();
    };
    const draw = () => {
      chosen.replaceChildren();
      for (const id of ids) {
        const t = todosById.get(id);
        if (!t) continue;
        const chip = el("button", "picker-chip", t.title + " ×");
        chip.type = "button";
        chip.setAttribute("aria-label", `Remove ${t.title}`);
        chip.addEventListener("click", () => toggle(id));
        chosen.appendChild(chip);
      }
      list.replaceChildren();
      // Nothing to show until something is typed; chosen todos are the chips above.
      list.hidden = !search.value.trim();
      if (list.hidden) return;
      const cands = Fields.pickerCandidates(todosById, todo.todo_id, search.value, ids, exclude);
      cands.slice(0, 40).forEach(({ todo: c, selected }) => {
        const btn = el("button", "picker-option" + (selected ? " is-selected" : ""), c.title);
        btn.type = "button";
        btn.setAttribute("aria-pressed", String(selected));
        btn.addEventListener("click", () => {
          // Picked: clear the search so the chip above is the only trace.
          if (!ids.has(c.todo_id)) search.value = "";
          toggle(c.todo_id);
        });
        list.appendChild(btn);
      });
      if (!cands.length) list.appendChild(el("p", "detail-empty", "No matching todos."));
    };
    search.addEventListener("input", draw);
    draw();
    wrap.append(chosen, search, list);
    return wrap;
  }

  // Not offered as blockers: relatives (see Fields.relativeIds) and containers, which never block.
  function blockerExclusions(todosById, todo) {
    const out = new Set(Fields.relativeIds(todosById, todo.todo_id));
    for (const t of todosById.values()) if (!Types.can(t, "hasCheckbox")) out.add(t.todo_id);
    return out;
  }

  // Everything the edit sheet needs: elements to append, and changes() which
  // returns { fields } (only what differs) or { error }.
  function renderEditFields(todo) {
    const { todosById } = deps.model;
    // Ids of vanished todos are dropped from both editor and baseline, so they
    // never trigger a write on their own.
    const present = (ids) => (ids || []).filter((id) => todosById.has(id));
    const base = { ...todo, blocked_by: present(todo.blocked_by), references: present(todo.references) };
    const state = {
      color: Fields.COLORS.includes(todo.color) ? todo.color : null,
      links: (todo.links || []).map((l) => ({ url: l.url, label: l.label || "" })),
    };
    const blocked = new Set(base.blocked_by);
    const refs = new Set(base.references);

    // Keyed by field name, so a sheet shows a group by looking the field up in the registry.
    const groups = {
      color: [label("Color"), renderColorPicker(state)],
      links: [label("Links"), renderLinksEditor(state)],
      blocked_by: [label("Blocked by"), renderTodoPicker(todo, blocked, blockerExclusions(todosById, todo))],
      references: [label("References"), renderTodoPicker(todo, refs)],
    };
    function changes() {
      const cleaned = Fields.cleanLinks(state.links);
      if (cleaned.error) return { error: cleaned.error };
      return { fields: Fields.changedFields(base, {
        color: state.color, links: cleaned.links, blocked_by: [...blocked], references: [...refs],
      }) };
    }
    return { groups, changes };
  }

  return { init, decorateRow, blockedChip, isRowTap, renderDetail, renderEditFields };
})();
