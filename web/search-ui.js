// Search UI. Loaded after app.js; uses its globals (model, focusTodo, API_BASE)
// and web/search.js for the matching. Everything is client-side over the tree
// already downloaded; trashed todos are fetched once per open from /todos/trash.
(function () {
  "use strict";

  const header = document.querySelector(".app-header");
  const main = document.querySelector(".app-main");

  const openBtn = document.createElement("button");
  openBtn.type = "button";
  openBtn.className = "search-open";
  openBtn.setAttribute("aria-label", "Search todos");
  openBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>';
  header.appendChild(openBtn);

  const bar = document.createElement("div");
  bar.className = "search-bar";
  bar.hidden = true;
  bar.setAttribute("role", "search");
  const input = document.createElement("input");
  input.type = "search";
  input.className = "search-input";
  input.placeholder = "Search todos";
  input.autocomplete = "off";
  input.setAttribute("enterkeyhint", "search");
  input.setAttribute("aria-label", "Search todos");
  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "search-btn";
  clearBtn.setAttribute("aria-label", "Clear search");
  clearBtn.textContent = "✕";
  clearBtn.hidden = true;
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "search-btn search-btn--text";
  closeBtn.textContent = "Cancel";
  bar.append(input, clearBtn, closeBtn);
  document.querySelector(".tabs-wrap").appendChild(bar);

  const results = document.createElement("section");
  results.id = "search-results";
  results.className = "search-results";
  results.hidden = true;
  results.setAttribute("aria-live", "polite");
  main.appendChild(results);

  // Trashed items matching the current query, from the server (paged, so never the whole
  // trash): { q, items }. Only shown while q is what is typed.
  let trash = null;
  let trashRequest = 0;
  let trashTimer = null;

  function isOpen() { return !bar.hidden; }

  function open() {
    if (isOpen()) { input.focus(); return; }
    bar.hidden = false;
    results.hidden = false;
    document.body.classList.add("searching");
    trash = null;
    render();
    input.focus();
  }

  function close() {
    if (!isOpen()) return;
    bar.hidden = true;
    results.hidden = true;
    document.body.classList.remove("searching");
    input.value = "";
    trashRequest++;
    clearTimeout(trashTimer);
    trash = null;
    openBtn.focus();
  }

  const TRASH_HITS = 10; // one page of matches is enough for a search box

  async function fetchTrash(q) {
    const mine = ++trashRequest;
    try {
      const response = await fetch(`${API_BASE}/trash?limit=${TRASH_HITS}&q=${encodeURIComponent(q)}`);
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      if (mine !== trashRequest) return;
      trash = { q, items: data.items || [] };
      render();
    } catch (e) {
      // Offline or failed: search just goes without the trash section.
    }
  }

  // The trash is searched on the server, a moment after typing stops.
  function scheduleTrashSearch() {
    clearTimeout(trashTimer);
    const q = input.value.trim();
    trashRequest++; // an answer for an older query is stale
    if (!q) { trash = null; return; }
    trashTimer = setTimeout(() => fetchTrash(q), 250);
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function render() {
    results.innerHTML = "";
    const q = input.value;
    clearBtn.hidden = q === "";
    if (!q.trim()) {
      results.appendChild(el("p", "next-note", "Search titles, links and colors."));
      return;
    }
    const hits = Search.search(model.todosById, q);
    const trashed = trash && trash.q === q.trim() ? trash.items : [];
    if (!hits.length && !trashed.length) {
      results.appendChild(el("p", "next-note", `No todos match “${q.trim()}”.`));
      return;
    }
    if (hits.length) {
      const list = el("ul", "search-list");
      for (const hit of hits) {
        const li = el("li");
        const btn = el("button", "search-hit" + (hit.todo.done && Types.can(hit.todo, "hasCheckbox") ? " is-done" : ""));
        btn.type = "button";
        if (hit.path.length) btn.appendChild(el("span", "search-path", hit.path.join(" › ")));
        btn.appendChild(el("span", "search-title", (hit.todo.done && Types.can(hit.todo, "hasCheckbox") ? "✓ " : "") + hit.todo.title));
        btn.addEventListener("click", (event) => {
          const y = event.detail === 0 ? btn.getBoundingClientRect().top : event.clientY;
          close();
          focusTodo(hit.todo.todo_id, y);
        });
        li.appendChild(btn);
        list.appendChild(li);
      }
      results.appendChild(list);
    }
    if (trashed.length) {
      results.appendChild(el("p", "next-caption search-section", "In Trash"));
      const list = el("ul", "search-list search-list--trash");
      for (const t of trashed) {
        const li = el("li");
        const btn = el("button", "search-hit is-done");
        btn.type = "button";
        btn.appendChild(el("span", "search-title", t.title));
        btn.appendChild(el("span", "search-path",
          `${Types.get(t).label} \u00b7 ${t.deleted_with ? `deleted with ${t.deleted_with}` : "deleted"} \u00b7 open in Trash`));
        btn.addEventListener("click", () => {
          close();
          window.Trash.open(t);
        });
        li.appendChild(btn);
        list.appendChild(li);
      }
      results.appendChild(list);
    }
  }

  openBtn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  clearBtn.addEventListener("click", () => { input.value = ""; scheduleTrashSearch(); render(); input.focus(); });
  input.addEventListener("input", () => { scheduleTrashSearch(); render(); });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen()) { event.preventDefault(); close(); }
  });
})();
