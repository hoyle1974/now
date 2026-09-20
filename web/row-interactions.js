// Row drag-to-reorder, long press and swipe wiring (attachRowInteractions).
// One of the app.js parts: classic scripts sharing one global scope, loaded in the
// order listed in index.html (top-level statements run in that order).
// The drag in progress, or null: { todoId, li }. Tracked here (not on the
// DOM) because every edit re-renders the whole list.
let dragState = null;
const LONG_PRESS_MS = 350;
const LONG_PRESS_SLOP = 8;

// Where a drop at (x, y) would land: the row under the pointer, or the nearest
// one when the pointer is between rows or beyond the ends, plus which part of
// the row it is on (above it, below it, or in its middle, meaning "nest").
function dropTargetAt(y) {
  const rows = [...document.querySelectorAll("#todo-tree .todo-row")]
    .filter((r) => !dragState.li.contains(r));
  if (!rows.length) return null;
  let best = null;
  let bestDistance = Infinity;
  for (const row of rows) {
    const rect = row.getBoundingClientRect();
    const distance = y < rect.top ? rect.top - y : y > rect.bottom ? y - rect.bottom : 0;
    if (distance < bestDistance) { best = { row, rect }; bestDistance = distance; }
  }
  const { row, rect } = best;
  const zone = bestDistance > 0
    ? (y < rect.top ? "before" : "after")
    : Reorder.zoneFor(rect, y);
  const li = row.closest("li");
  const plan = Reorder.planDrop(model, dragState.todoId, li.dataset.todoId, zone);
  return { row, li, zone, plan };
}

let dropLine = null;
let dropRow = null;

function clearDropHint() {
  if (dropLine) dropLine.hidden = true;
  if (dropRow) dropRow.classList.remove("drop-inside");
  dropRow = null;
}

function showDropHint(target) {
  clearDropHint();
  if (!target || !target.plan) return;
  if (target.zone === "inside") {
    dropRow = target.row;
    dropRow.classList.add("drop-inside");
    return;
  }
  if (!dropLine) {
    dropLine = document.createElement("div");
    dropLine.className = "drop-line";
    document.body.appendChild(dropLine);
  }
  // "Below" a row that has children means below its whole subtree.
  const rect = (target.zone === "before" ? target.row : target.li).getBoundingClientRect();
  const rowRect = target.row.getBoundingClientRect();
  dropLine.style.left = `${rowRect.left + 8}px`;
  dropLine.style.width = `${rowRect.width - 16}px`;
  dropLine.style.top = `${(target.zone === "before" ? rect.top : rect.bottom) - 1.5}px`;
  dropLine.hidden = false;
}

// Applies the drop: one reparent op (optimistic, queued like any edit).
function commitDrop(target) {
  const state = dragState;
  dragState = null;
  clearDropHint();
  if (!state || !target || !target.plan || !engine.enqueue({
    kind: "reparent", target_id: state.todoId, payload: target.plan,
  })) {
    renderTree();
    return;
  }
  // Show what was just dropped into.
  if (target.plan.parent_id) setCollapsed(target.plan.parent_id, false);
}

// #1 & #5: Swipe gestures and title tap-to-rename
function attachRowInteractions(row, todo) {
  let touchStartX = 0;
  let touchStartY = 0;
  let swiping = false;

  row.addEventListener("touchstart", (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    swiping = false;

    if (e.target.closest(".todo-drag-handle")) touchStartX = 0;
  }, { passive: true });

  row.addEventListener("touchmove", (e) => {
    if (!touchStartX) return;
    const deltaX = e.touches[0].clientX - touchStartX;
    const deltaY = e.touches[0].clientY - touchStartY;

    // If dragging (long-press active), stop swipe detection
    if (row.classList.contains("dragging")) {
      swiping = false;
      return;
    }

    // Only swipe horizontally (not vertical scroll)
    if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 30) {
      swiping = true;
    }
  }, { passive: true });

  row.addEventListener("touchend", (e) => {
    if (!touchStartX) return;

    const isDragging = row.classList.contains("dragging");
    const deltaX = e.changedTouches[0].clientX - touchStartX;
    const deltaY = e.changedTouches[0].clientY - touchStartY;

    // Handle drag reordering (vertical movement while dragging)
    if (isDragging && Math.abs(deltaY) > 30) {
      row.classList.remove("dragging");
      row.style.opacity = "1";
      const direction = deltaY > 0 ? "down" : "up";
      reportedFailure(moveTodo(todo.todo_id, direction));
      touchStartX = 0;
      return;
    }

    // Clear drag state
    if (isDragging) {
      row.classList.remove("dragging");
      row.style.opacity = "1";
      touchStartX = 0;
      return;
    }

    if (!swiping || !touchStartX) return;

    // Swipe right: mark done
    if (deltaX > 60) {
      const checkbox = row.querySelector('input[type="checkbox"]');
      if (checkbox && !checkbox.checked) {
        checkbox.checked = true;
        celebrate(todo.todo_id);
        reportedFailure(toggleDone(todo.todo_id, true));
      }
    }
    // Swipe left: delete
    else if (deltaX < -60) {
      setActivePanel(null);
      reportedFailure(deleteTodo(todo.todo_id));
    }

    touchStartX = 0;
  });

  // #5: Tap title to rename
  const titleEl = row.querySelector('.todo-title');
  if (titleEl && !todo.done) {
    titleEl.style.cursor = 'text';
    titleEl.addEventListener('click', (e) => {
      if (e.detail === 2) { // Double-click
        e.stopPropagation();
        const input = document.createElement('input');
        input.type = 'text';
        input.value = todo.title;
        input.style.cssText = 'font-size:inherit; font-weight:inherit; border:1px solid; padding:4px; border-radius:6px;';
        const originalEl = titleEl;

        titleEl.replaceWith(input);
        input.focus();
        input.select();

        let finished = false; // Escape/Enter/blur must act once (removing the input fires blur)
        const save = async () => {
          if (finished) return;
          finished = true;
          const newTitle = input.value.trim();
          if (newTitle && newTitle !== todo.title) {
            await reportedFailure(saveEdit(todo.todo_id, newTitle, undefined));
          } else {
            renderTree();
          }
        };

        input.addEventListener('blur', save);
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') save();
          if (e.key === 'Escape') { finished = true; renderTree(); }
        });
      }
    });
  }
}

