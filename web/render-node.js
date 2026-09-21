// renderNode: one todo row and its subtree.
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).
// Done rows display below the open ones in their group, each part keeping its
// stored order (this never touches order_idx). A row that was just completed
// stays put until its animation ends.
function sinkDone(todos) {
  const sunk = (t) => t.done && Types.can(t, "hasCheckbox") && !justCompleted.has(t.todo_id);
  return [...todos.filter((t) => !sunk(t)), ...todos.filter(sunk)];
}

function renderNode(todo, todosById, descendantCounts, depth = 0) {
  const li = document.createElement("li");
  li.className = "todo-node";
  li.dataset.todoId = todo.todo_id;
  li.style.setProperty("--depth", depth);
  const hasChildren = todo.child_ids.length > 0;
  const isCollapsed = hasChildren && todo.collapsed;

  // A row shows only its own stored state: a done parent does not make its
  // subtasks look done, and they can still be checked and unchecked.
  const hasCheckbox = Types.can(todo, "hasCheckbox");
  const shownDone = hasCheckbox && todo.done;
  const row = document.createElement("div");
  row.className = "todo-row";
  if (shownDone) {
    row.classList.add("is-done");
  }
  if (justCompleted.has(todo.todo_id) && shownDone) {
    row.classList.add("just-done");
  }
  if (focusedId === todo.todo_id) {
    row.classList.add("is-focused");
  }

  // Long-press a row to drag it: drop above/below another row to move there, or
  // onto the middle of a row to make it a subtask of that row.
  if (model.todosById.size > 1) {
    // Hard press: the drag only starts after a long-press anywhere on the row
    // (so scrolling and taps are untouched). Moving before the threshold is a
    // scroll and cancels; when armed the row lifts (with a small buzz where
    // supported) and the finger can then drag it.
    row.addEventListener("contextmenu", (e) => { if (pressing) e.preventDefault(); });
    let pressing = false;
    // Registered up front (non-passive) so iOS lets us stop the scroll once armed.
    row.addEventListener("touchmove", (t) => { if (dragState && t.cancelable) t.preventDefault(); }, { passive: false });
    row.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || dragState) return;
      if (e.target.closest("input, textarea, label, a, button:not(.todo-drag-handle)")) return;
      const pid = e.pointerId;
      let lastY = e.clientY;
      pressing = true;
      const stop = () => {
        pressing = false;
        press.end();
        row.classList.remove("armed");
        window.removeEventListener("pointermove", onPreMove);
        window.removeEventListener("pointerup", onPreEnd);
        window.removeEventListener("pointercancel", onPreEnd);
      };
      const press = Reorder.longPress(() => {
        if (!row.isConnected) { stop(); return; }
        row.classList.add("armed");
        try { navigator.vibrate && navigator.vibrate(12); } catch (_) { /* optional */ }
        window.removeEventListener("pointermove", onPreMove);
        window.removeEventListener("pointerup", onPreEnd);
        window.removeEventListener("pointercancel", onPreEnd);
        beginDrag(pid, lastY);
      }, { delay: LONG_PRESS_MS, slop: LONG_PRESS_SLOP });
      const onPreMove = (m) => {
        if (m.pointerId !== pid) return;
        lastY = m.clientY;
        press.move(m.clientX, m.clientY);
      };
      const onPreEnd = (u) => { if (u.pointerId === pid) stop(); };
      window.addEventListener("pointermove", onPreMove);
      window.addEventListener("pointerup", onPreEnd);
      window.addEventListener("pointercancel", onPreEnd);
      press.start(e.clientX, e.clientY);
    });

    const beginDrag = (pid, startY) => {
      pressing = false;
      row.classList.remove("armed");
      const rowRect = row.getBoundingClientRect();
      const grabY = startY - rowRect.top;
      dragState = { todoId: String(todo.todo_id), li };
      row.classList.add("dragging");

      const ghost = row.cloneNode(true);
      ghost.classList.remove("dragging");
      ghost.style.cssText = `position:fixed;left:${rowRect.left}px;top:0;width:${rowRect.width}px;
        pointer-events:none;z-index:10000;background:var(--card);border-radius:12px;
        box-shadow:0 8px 24px rgba(0,0,0,0.2);will-change:transform;
        transform:translate3d(0,${rowRect.top}px,0) scale(1.03);`;
      document.body.appendChild(ghost);

      // Track the gesture on window: the row can re-render under the finger.
      let pointerY = startY;
      let target = null;
      let scrollTimer = null;
      const update = () => {
        ghost.style.transform = `translate3d(0,${pointerY - grabY}px,0) scale(1.03)`;
        target = dropTargetAt(pointerY);
        showDropHint(target);
      };
      // Near the top or bottom edge, scroll so far-away rows can be reached.
      const autoScroll = () => {
        const edge = 90;
        const speed = pointerY < edge ? -(edge - pointerY) / 6
          : pointerY > window.innerHeight - edge ? (pointerY - (window.innerHeight - edge)) / 6 : 0;
        if (speed) { window.scrollBy(0, speed); update(); }
        scrollTimer = requestAnimationFrame(autoScroll);
      };
      scrollTimer = requestAnimationFrame(autoScroll);
      const onMove = (m) => {
        if (m.pointerId !== pid) return;
        m.preventDefault();
        pointerY = m.clientY;
        update();
      };
      const blockScroll = (t) => t.preventDefault();
      const onEnd = (u) => {
        if (u.pointerId !== pid) return;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onEnd);
        window.removeEventListener("pointercancel", onEnd);
        window.removeEventListener("touchmove", blockScroll);
        cancelAnimationFrame(scrollTimer);
        ghost.remove();
        row.classList.remove("dragging");
        // A cancelled gesture (incoming call, etc.) drops nothing.
        commitDrop(u.type === "pointercancel" ? null : target);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onEnd);
      window.addEventListener("pointercancel", onEnd);
      window.addEventListener("touchmove", blockScroll, { passive: false });
      update();
    };
  }

  // A container (list/project) has no done state, so its slot holds a marker instead.
  const checkboxHit = document.createElement(hasCheckbox ? "label" : "span");
  checkboxHit.className = hasCheckbox ? "todo-check" : "todo-check todo-check--none";
  if (!hasCheckbox) checkboxHit.appendChild(icon(Types.get(todo).icon));
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = shownDone;
  checkbox.setAttribute("aria-label", `Mark "${todo.title}" ${shownDone ? "not done" : "done"}`);
  checkbox.addEventListener("change", () => {
    // #3: Instant checkbox response - update UI immediately
    const wasChecked = checkbox.checked;
    if (wasChecked) {
      row.classList.add("is-done");
      celebrate(todo.todo_id);
    } else {
      row.classList.remove("is-done");
    }
    reportedFailure(toggleDone(todo.todo_id, checkbox.checked));
  });
  if (hasCheckbox) checkboxHit.appendChild(checkbox);

  const body = document.createElement("div");
  body.className = "todo-body";
  const label = document.createElement("span");
  label.className = "todo-title";
  label.textContent = todo.title;
  body.append(label, renderMeta(todo, hasChildren, descendantCounts.get(todo.todo_id)));

  const trailing = document.createElement("div");
  trailing.className = "todo-trailing";

  if (hasChildren) {
    const toggle = iconButton("todo-toggle", "chevron", isCollapsed ? "Expand subtasks" : "Collapse subtasks");
    toggle.setAttribute("aria-expanded", String(!isCollapsed));
    toggle.addEventListener("click", () => {
      setCollapsed(todo.todo_id, !todo.collapsed);
      renderTree();
    });
    trailing.appendChild(toggle);
  }

  const menuWrap = document.createElement("div");
  menuWrap.className = "todo-menu";

  const kebabBtn = iconButton("todo-kebab", "more", "More actions");
  kebabBtn.setAttribute("aria-haspopup", "menu");
  const menuOpen = isActivePanel("menu", todo.todo_id);
  kebabBtn.setAttribute("aria-expanded", String(menuOpen));
  kebabBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    setActivePanel(menuOpen ? null : "menu", todo.todo_id);
    renderTree();
  });
  menuWrap.appendChild(kebabBtn);

  if (menuOpen) {
    const menu = document.createElement("div");
    menu.className = "todo-menu-dropdown";
    menu.setAttribute("role", "menu");

    const openPanel = (mode) => () => {
      setActivePanel(mode, todo.todo_id);
      renderTree();
    };
    menu.append(
      menuItem("Add item", "plus", openPanel("add")),
      menuItem("Add several", "split", openPanel("split")),
      menuItem("Edit", "pencil", openPanel("edit")),
      // One entry however many types there are; switching only changes the label:
      // due date, repeat and done stay, inactive.
      menuItem(`Type: ${TypeUI.labelOf(Types.nameOf(todo))}`, Types.get(todo).icon, openPanel("type"))
    );

    menu.append(
      menuItem("Copy with subtasks", "copy", () => {
        setActivePanel(null);
        renderTree();
        copyOutline(todo.todo_id);
      })
    );

    menu.append(
      menuItem("Move up", "up", () => reportedFailure(moveTodo(todo.todo_id, "up"))),
      menuItem("Move down", "down", () => reportedFailure(moveTodo(todo.todo_id, "down")))
    );

    menu.append(
      menuItem(
        "Delete",
        "trash",
        () => {
          setActivePanel(null);
          reportedFailure(deleteTodo(todo.todo_id));
        },
        "todo-menu-item--danger"
      )
    );
    menuWrap.appendChild(menu);
  }

  trailing.appendChild(menuWrap);

  // Assemble row: checkbox, body, trailing controls
  row.append(checkboxHit, body, trailing);
  if (hasChildren && !isCollapsed) {
    // Stem from this checkbox down to its subtasks (see .todo-stem).
    const stem = document.createElement("span");
    stem.className = "todo-stem";
    stem.setAttribute("aria-hidden", "true");
    row.appendChild(stem);
  }
  li.appendChild(row);

  // Color accent, and a folded detail panel that a tap on the row body opens.
  FieldsUI.decorateRow(row, todo);
  row.addEventListener("click", (e) => {
    if (!FieldsUI.isRowTap(e.target) || row.classList.contains("dragging")) return;
    // A plain tap must not throw away an open editor with typed text.
    if (activePanel && ["add", "split", "edit"].includes(activePanel.mode) &&
        [...document.querySelectorAll("#todo-tree .sheet input, #todo-tree .sheet textarea")]
          .some((f) => f.type !== "date" && f.type !== "time" && f.value.trim())) return;
    setActivePanel("view", todo.todo_id);
    renderTree();
  });

  // Attach swipe/tap interactions
  attachRowInteractions(row, todo);

  if (isActivePanel("split", todo.todo_id)) {
    li.appendChild(renderSplitEditor(todo));
  }

  if (isActivePanel("add", todo.todo_id)) {
    li.appendChild(ItemForm.render({ mode: "create", parent: todo }));
  }

  if (isActivePanel("edit", todo.todo_id)) {
    li.appendChild(ItemForm.render({ mode: "edit", todo }));
  }

  if (isActivePanel("type", todo.todo_id)) {
    li.appendChild(renderTypePanel(todo));
  }

  if (isActivePanel("view", todo.todo_id)) {
    li.appendChild(renderViewer(todo, descendantCounts.get(todo.todo_id)));
  }

  if (hasChildren && !isCollapsed) {
    const childList = document.createElement("ul");
    childList.className = "todo-children";
    // Sort children by order_idx (respecting manual reordering), then by urgency
    const children = sinkDone(todo.child_ids
      .map((id) => todosById.get(id))
      .sort((a, b) => {
        // Primary sort: by order_idx (respects drag-and-drop reordering)
        const aOrder = a.order_idx ?? 999999;
        const bOrder = b.order_idx ?? 999999;
        if (aOrder !== bOrder) return aOrder - bOrder;

        // Secondary sort: by urgency (within same order)
        const aUrgent = isUrgent(a);
        const bUrgent = isUrgent(b);
        if (aUrgent !== bUrgent) return aUrgent ? -1 : 1;
        if (aUrgent && bUrgent) return new Date(a.due_date) - new Date(b.due_date);
        return 0;
      }));
    for (const child of children) {
      childList.appendChild(renderNode(child, todosById, descendantCounts, depth + 1));
    }
      li.appendChild(childList);
  }

  return li;
}

