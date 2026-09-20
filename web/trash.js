// "Clear completed" and the Trash view. Loaded after app.js and uses its
// globals (model, engine, setTab, showNotice, loadAndRender, ...).
//
// Clear completed is one outbox op (`clear_completed`, see sync.js), so it is
// optimistic and offline-safe. The Trash view lists soft-deleted todos from
// GET /todos/trash and restores them with the ordinary `undelete` op.
(function () {
  "use strict";

  const main = document.querySelector(".app-main");

  // ---- footer under the list: Clear completed + Trash link ------------------
  const footer = document.createElement("div");
  footer.className = "list-footer";
  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "footer-btn";
  clearBtn.hidden = true;
  const trashLink = document.createElement("button");
  trashLink.type = "button";
  trashLink.className = "footer-btn footer-btn--quiet";
  trashLink.textContent = "Trash";
  footer.append(clearBtn, trashLink);
  treeEl.after(footer);

  function updateFooter() {
    const n = Sync.clearableIds(model).length;
    clearBtn.hidden = n === 0;
    clearBtn.textContent = `Clear ${n} completed`;
    clearBtn.title = "Removes done todos (and done subtasks) to Trash";
  }
  // Every render rebuilds the list, so refresh the count when it changes.
  new MutationObserver(updateFooter).observe(treeEl, { childList: true });
  updateFooter();

  // A toast with an Undo button, in the same element and style as showUndo.
  function showUndoToast(message, onUndo) {
    const errorDiv = document.getElementById("error");
    const token = "toast:" + Date.now();
    clearTimeout(undoTimer);
    lastDeleted = token; // keeps apiFetch from wiping the toast
    errorDiv.onclick = null;
    errorDiv.hidden = false;
    errorDiv.textContent = message + " · ";
    const btn = document.createElement("button");
    btn.textContent = "Undo";
    btn.className = "toast-action";
    btn.onclick = () => {
      clearTimeout(undoTimer);
      errorDiv.hidden = true;
      lastDeleted = null;
      onUndo();
    };
    errorDiv.appendChild(btn);
    undoTimer = setTimeout(() => {
      if (lastDeleted === token) {
        errorDiv.hidden = true;
        lastDeleted = null;
      }
    }, 8000);
  }

  function clearCompleted() {
    const ids = Sync.clearableIds(model);
    if (!ids.length) return;
    if (!engine.enqueue({ kind: "clear_completed", target_id: "clear-completed" })) return;
    showUndoToast(ids.length === 1 ? "Cleared 1 completed" : `Cleared ${ids.length} completed`, () => {
      for (const id of ids) engine.enqueue({ kind: "undelete", target_id: id });
    });
  }
  clearBtn.addEventListener("click", clearCompleted);

  // ---- Trash view -----------------------------------------------------------
  const view = document.createElement("section");
  view.id = "trash-view";
  view.className = "trash-view";
  view.hidden = true;
  const bar = document.createElement("div");
  bar.className = "trash-bar";
  const back = document.createElement("button");
  back.type = "button";
  back.className = "footer-btn";
  back.textContent = "‹ Back";
  const caption = document.createElement("p");
  caption.className = "next-caption";
  caption.textContent = "Trash";
  bar.append(back, caption);
  const list = document.createElement("ul");
  list.className = "trash-list";
  const note = document.createElement("p");
  note.className = "next-note";
  view.append(bar, list, note);
  main.appendChild(view);

  let items = null;
  let request = 0;

  function renderTrash() {
    list.innerHTML = "";
    if (items === null) {
      note.hidden = false;
      note.textContent = "Loading…";
      return;
    }
    note.hidden = items.length > 0;
    note.textContent = "Trash is empty.";
    for (const item of items) {
      const li = document.createElement("li");
      li.className = "trash-row";
      const title = document.createElement("span");
      title.className = "trash-title" + (item.done ? " is-done" : "");
      title.textContent = item.title;
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "trash-restore";
      restore.textContent = "Undelete";
      restore.addEventListener("click", () => undelete(item));
      li.append(title, restore);
      list.appendChild(li);
    }
  }

  async function refreshTrash() {
    const mine = ++request;
    // Unsent deletes aren't on the server yet: let them land first.
    await Promise.race([engine.flush(), new Promise((resolve) => setTimeout(resolve, 4000))]);
    try {
      const response = await fetch(`${API_BASE}/trash`);
      if (!response.ok) throw new Error(`${response.status}`);
      const data = await response.json();
      if (mine !== request) return;
      items = data.items;
      note.textContent = "Trash is empty.";
    } catch (err) {
      logEvent("trash-fail", err.message);
      if (mine !== request) return;
      if (items === null) items = [];
      showNotice({ level: "info", message: "Couldn't load the trash. Are you offline?" });
    }
    renderTrash();
  }

  function undelete(item) {
    if (!engine.enqueue({ kind: "undelete", target_id: item.todo_id })) return;
    items = items.filter((i) => i.todo_id !== item.todo_id);
    renderTrash();
    showNotice({ level: "info", message: "Restored" });
    // The restored subtree isn't in the local model (it was deleted before this
    // page loaded), so reload the tree once the restore has been sent.
    reportedFailure(engine.flush().then(() => loadAndRender()));
  }

  back.addEventListener("click", () => setTab("list"));
  trashLink.addEventListener("click", () => setTab("trash"));

  window.Trash = {
    onTab(tab) {
      view.hidden = tab !== "trash";
      if (tab === "trash") {
        items = null;
        renderTrash();
        reportedFailure(refreshTrash());
      }
    },
  };
})();
