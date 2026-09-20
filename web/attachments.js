// Pure helpers for image attachments. No DOM access, so it runs unchanged under
// `node --test`. The limits mirror app/models.py; the server enforces them again.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Attachments = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const MAX_BYTES = 10 * 1024 * 1024;
  const MAX_PER_TODO = 10;
  const TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];
  const TYPE_MESSAGE = "Only JPEG, PNG, GIF and WebP images can be attached.";

  // Returns an error message, or null when the file can be uploaded.
  function checkFile(file, existingCount) {
    if (!TYPES.includes(file.type)) return TYPE_MESSAGE;
    if (!file.size) return "That file is empty.";
    if (file.size > MAX_BYTES) return "Images can be at most 10 MB.";
    if (existingCount >= MAX_PER_TODO) return `A todo can have at most ${MAX_PER_TODO} images.`;
    return null;
  }

  // Image files from a FileList, or from clipboard/drag items (which need getAsFile).
  function imageFiles(list) {
    const out = [];
    for (const entry of Array.from(list || [])) {
      const f = typeof entry.getAsFile === "function"
        ? (entry.kind === "file" ? entry.getAsFile() : null)
        : entry;
      if (f && typeof f.type === "string" && f.type.startsWith("image/")) out.push(f);
    }
    return out;
  }

  function attachmentPath(todoId, attachmentId) {
    const base = `/todos/${todoId}/attachments`;
    return attachmentId ? `${base}/${attachmentId}` : base;
  }

  // status 0 = the request never got an answer.
  function uploadError(status, detail) {
    if (status === 0) return "You appear to be offline. Images can only be added while connected.";
    if (status === 413) return "Images can be at most 10 MB.";
    if (status === 404) return "That todo no longer exists.";
    if (status === 400 && detail) return detail.charAt(0).toUpperCase() + detail.slice(1) + ".";
    if (status === 400) return TYPE_MESSAGE;
    return "Couldn't upload the image. Please try again.";
  }

  // A todo created offline has a temporary id until it syncs; the server can't
  // attach anything to it yet.
  function canUpload(todo) {
    return !String(todo.todo_id).startsWith("tmp:");
  }

  return { MAX_BYTES, MAX_PER_TODO, TYPES, checkFile, imageFiles, attachmentPath, uploadError, canUpload };
});
