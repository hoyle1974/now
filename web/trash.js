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

  function clearCompleted() {
    const ids = Sync.clearableIds(model);
    if (!ids.length) return;
    if (!engine.enqueue({ kind: "clear_completed", target_id: "clear-completed" })) return;
    toast.show({
      message: ids.length === 1 ? "Cleared 1 completed" : `Cleared ${ids.length} completed`,
      ttl: 8000,
      action: { label: "Undo", run: () => { for (const id of ids) engine.enqueue({ kind: "undelete", target_id: id }); } },
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
  const more = DOM.button("Load more", "footer-btn trash-more");
  more.hidden = true;
  view.append(bar, list, note, more);
  main.appendChild(view);

  const PAGE = 50; // items per request (the server caps a page at 100)
  let items = null;
  let hasMore = false;
  let nextOffset = 0;
  let request = 0;
  let viewer = null;

  function renderTrash() {
    list.innerHTML = "";
    if (items === null) {
      note.hidden = false;
      note.textContent = "Loading…";
      return;
    }
    note.hidden = items.length > 0;
    note.textContent = "Trash is empty.";
    more.hidden = !hasMore;
    for (const item of items) {
      const done = item.done && Types.can(item, "hasCheckbox");
      const kind = Types.get(item).label;
      const open = DOM.button("", "trash-open", () => openViewer(item));
      open.append(
        DOM.el("span", "trash-type", null),
        DOM.el("span", "trash-text", null)
      );
      open.firstChild.appendChild(icon(Types.get(item).icon));
      open.lastChild.append(
        DOM.el("span", "trash-title" + (done ? " is-done" : ""), item.title),
        DOM.el("span", "trash-note", item.deleted_with ? `${kind} \u00b7 in ${item.deleted_with}` : kind)
      );
      const li = DOM.el("li", "trash-row");
      li.append(open, DOM.button("Undelete", "trash-restore", () => undelete(item)));
      list.appendChild(li);
    }
  }

  async function refreshTrash() {
    const mine = ++request;
    // Unsent deletes aren't on the server yet: let them land first.
    await Promise.race([engine.flush(), new Promise((resolve) => setTimeout(resolve, 4000))]);
    try {
      const data = await fetchPage(0);
      if (mine !== request) return;
      items = data.items;
      hasMore = data.has_more;
      nextOffset = data.next_offset;
      note.textContent = "Trash is empty.";
    } catch (err) {
      logEvent("trash-fail", err.message);
      if (mine !== request) return;
      if (items === null) items = [];
      showNotice({ level: "info", message: "Couldn't load the trash. Are you offline?" });
    }
    renderTrash();
  }

  async function fetchPage(offset) {
    const response = await fetch(`${API_BASE}/trash?limit=${PAGE}&offset=${offset}`);
    if (!response.ok) throw new Error(`${response.status}`);
    return response.json();
  }

  async function loadMore() {
    const mine = request;
    more.disabled = true;
    try {
      const data = await fetchPage(nextOffset);
      if (mine !== request) return;
      const have = new Set(items.map((i) => i.todo_id));
      items = items.concat(data.items.filter((i) => !have.has(i.todo_id)));
      hasMore = data.has_more;
      nextOffset = data.next_offset;
    } catch (err) {
      logEvent("trash-fail", err.message);
      showNotice({ level: "info", message: "Couldn't load more. Are you offline?" });
    } finally {
      more.disabled = false;
    }
    renderTrash();
  }
  more.addEventListener("click", loadMore);

  // A deleted item opens read-only, as it was when deleted; Undelete is there too.
  function openViewer(item) {
    closeViewer();
    viewer = renderViewer(item, null, {
      deleted_with: item.deleted_with,
      trashed_at: item.trashed_at,
      onClose: closeViewer,
      onRestore: () => { closeViewer(); undelete(item); },
    });
    view.appendChild(viewer);
    document.body.style.overflow = "hidden";
  }

  function closeViewer() {
    if (viewer) viewer.remove();
    viewer = null;
    document.body.style.overflow = "";
  }

  function undelete(item) {
    if (!engine.enqueue({ kind: "undelete", target_id: item.todo_id })) return;
    if (items) items = items.filter((i) => i.todo_id !== item.todo_id);
    renderTrash();
    showNotice({ level: "info", message: "Restored" });
    // The restored subtree isn't in the local model (it was deleted before this page loaded),
    // so reload the tree once the restore has been sent. Restoring an item inside a deleted
    // parent restores the parent chain too, so the trash list is reloaded as well.
    reportedFailure(engine.flush().then(() => loadAndRender()).then(() => {
      if (!view.hidden) return refreshTrash();
      return undefined;
    }));
  }

  back.addEventListener("click", () => setTab("list"));
  trashLink.addEventListener("click", () => setTab("trash"));

  window.Trash = {
    // Show the Trash page with one item open (a search hit): the item is already in hand,
    // so it does not depend on which page of the trash it would be on.
    open(item) {
      setTab("trash");
      openViewer(item);
    },
    onTab(tab) {
      view.hidden = tab !== "trash";
      closeViewer();
      if (tab === "trash") {
        items = null;
        renderTrash();
        reportedFailure(refreshTrash());
      }
    },
  };
})();
