// DOM for image attachments: the "Images" section of the todo viewer (thumbnails,
// add button, paste and drop) and the full-size lightbox. Bytes come from the
// authenticated API (auth.js wraps fetch), so images are fetched and shown as
// blob URLs rather than <img src>. Online only: nothing is queued offline.
// Depends on Attachments (attachments.js); app.js hands it the model.
const AttachmentsUI = (() => {
  let deps = { model: null, notify: () => {}, observeRev: () => {}, onChange: () => {} };
  // "todoId/attachmentId" -> Promise<blob URL>. An attachment never changes, so
  // one fetch per page load is enough.
  const blobUrls = new Map();
  // The section currently on screen, so a paste anywhere in the page reaches it.
  let mounted = null;

  function init(d) {
    deps = { ...deps, ...d };
    document.addEventListener("paste", (e) => {
      if (!mounted || !mounted.root.isConnected) return;
      const files = Attachments.imageFiles(e.clipboardData && e.clipboardData.items);
      if (!files.length) return;
      e.preventDefault();
      mounted.upload(files);
    });
  }

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };

  function blobUrl(todoId, attachmentId) {
    const key = `${todoId}/${attachmentId}`;
    if (!blobUrls.has(key)) {
      const pending = fetch(Attachments.attachmentPath(todoId, attachmentId))
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.blob();
        })
        .then((blob) => URL.createObjectURL(blob));
      pending.catch(() => blobUrls.delete(key)); // let a later render retry
      blobUrls.set(key, pending);
    }
    return blobUrls.get(key);
  }

  // ---- lightbox -------------------------------------------------------------

  function openLightbox(todoId, attachment, onRemove) {
    const overlay = el("div", "lightbox");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", attachment.name);
    const img = el("img", "lightbox-img");
    img.alt = attachment.name;
    const bar = el("div", "lightbox-bar");
    const close = () => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(); }
    };
    const closeBtn = el("button", "btn btn-plain", "Close");
    closeBtn.type = "button";
    closeBtn.addEventListener("click", close);
    const removeBtn = el("button", "btn btn-plain lightbox-remove", "Remove");
    removeBtn.type = "button";
    let armed = null;
    removeBtn.addEventListener("click", () => {
      if (!armed) {
        removeBtn.textContent = "Tap again to remove";
        armed = setTimeout(() => { armed = null; removeBtn.textContent = "Remove"; }, 3000);
        return;
      }
      clearTimeout(armed);
      close();
      onRemove();
    });
    bar.append(closeBtn, removeBtn);
    overlay.append(img, bar);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    blobUrl(todoId, attachment.id).then((url) => { img.src = url; }, () => {
      overlay.insertBefore(el("p", "lightbox-error", "Couldn't load this image."), bar);
    });
    closeBtn.focus();
  }

  // ---- the section ----------------------------------------------------------

  function renderSection(todo) {
    const root = el("div", "attachments");
    root.appendChild(el("p", "detail-heading", "Images"));
    const grid = el("div", "attachment-grid");
    const status = el("p", "detail-empty attachment-status");
    status.hidden = true;
    const input = el("input");
    input.type = "file";
    input.accept = Attachments.TYPES.join(",");
    input.multiple = true;
    input.hidden = true;
    const addBtn = el("button", "btn btn-plain attachment-add", "Add image");
    addBtn.type = "button";
    addBtn.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      const files = Attachments.imageFiles(input.files);
      input.value = "";
      upload(files);
    });
    root.append(grid, status, addBtn, input);

    // Read through the model each time: the node is replaced when the tree is
    // rebuilt from the server, and this section may outlive that.
    const node = () => deps.model.todosById.get(todo.todo_id) || todo;
    const list = () => node().attachments || [];
    const say = (text) => { status.textContent = text || ""; status.hidden = !text; };

    function draw() {
      grid.replaceChildren();
      for (const a of list()) {
        const thumb = el("button", "attachment-thumb");
        thumb.type = "button";
        thumb.setAttribute("aria-label", `View ${a.name}`);
        const img = el("img");
        img.alt = "";
        img.loading = "lazy";
        thumb.appendChild(img);
        blobUrl(todo.todo_id, a.id).then((url) => { img.src = url; },
          () => thumb.classList.add("is-broken"));
        thumb.addEventListener("click", () => openLightbox(todo.todo_id, a, () => remove(a)));
        grid.appendChild(thumb);
      }
      grid.hidden = !list().length;
      addBtn.disabled = !Attachments.canUpload(todo) || list().length >= Attachments.MAX_PER_TODO;
      if (!Attachments.canUpload(todo)) say("Images can be added once this todo has synced.");
    }

    function adopt(body, headers) {
      const n = node();
      n.attachments = body.attachments;
      n.version = body.version;
      deps.observeRev(headers.prev, headers.rev);
    }

    const revHeaders = (r) => {
      const num = (name) => (r.headers.get(name) === null ? undefined : Number(r.headers.get(name)));
      return { prev: num("X-Rev-Prev"), rev: num("X-Rev") };
    };

    async function readDetail(response) {
      try { return (await response.json()).detail; } catch { return undefined; }
    }

    let busy = false;
    async function upload(files) {
      if (busy || !files.length || !Attachments.canUpload(todo)) return;
      busy = true;
      addBtn.disabled = true;
      try {
        for (const file of files) {
          const problem = Attachments.checkFile(file, list().length);
          if (problem) { deps.notify(problem); break; }
          say(`Uploading ${file.name || "image"}…`);
          let response;
          try {
            const form = new FormData();
            form.append("file", file, file.name || "image");
            response = await fetch(Attachments.attachmentPath(todo.todo_id), { method: "POST", body: form });
          } catch {
            deps.notify(Attachments.uploadError(0));
            break;
          }
          if (!response.ok) {
            deps.notify(Attachments.uploadError(response.status, await readDetail(response)));
            break;
          }
          adopt(await response.json(), revHeaders(response));
          draw();
        }
      } finally {
        busy = false;
        say("");
        draw();
      }
    }

    async function remove(a) {
      let response;
      try {
        response = await fetch(Attachments.attachmentPath(todo.todo_id, a.id), { method: "DELETE" });
      } catch {
        deps.notify("You appear to be offline. Images can only be removed while connected.");
        return;
      }
      if (response.status === 404) {
        // Already gone (removed elsewhere): drop it locally too.
        node().attachments = list().filter((x) => x.id !== a.id);
      } else if (!response.ok) {
        deps.notify("Couldn't remove the image. Please try again.");
        return;
      } else {
        adopt(await response.json(), revHeaders(response));
      }
      draw();
    }

    // Drop image files anywhere on the section.
    root.addEventListener("dragover", (e) => {
      if (Array.from((e.dataTransfer && e.dataTransfer.types) || []).includes("Files")) {
        e.preventDefault();
        root.classList.add("is-dropping");
      }
    });
    root.addEventListener("dragleave", () => root.classList.remove("is-dropping"));
    root.addEventListener("drop", (e) => {
      root.classList.remove("is-dropping");
      const files = Attachments.imageFiles(e.dataTransfer && e.dataTransfer.files);
      if (!files.length) return;
      e.preventDefault();
      upload(files);
    });

    draw();
    mounted = { root, upload };
    return root;
  }

  return { init, renderSection };
})();
