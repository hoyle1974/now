"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Attachments = require("../web/attachments.js");

const file = (type, size = 100, name = "a") => ({ type, size, name });

test("limits match the server", () => {
  assert.equal(Attachments.MAX_BYTES, 10 * 1024 * 1024);
  assert.equal(Attachments.MAX_PER_TODO, 10);
});

test("checkFile accepts the four image types", () => {
  for (const t of ["image/jpeg", "image/png", "image/gif", "image/webp"]) {
    assert.equal(Attachments.checkFile(file(t), 0), null);
  }
});

test("checkFile rejects other types, empty files, oversize files, and a full todo", () => {
  assert.match(Attachments.checkFile(file("image/svg+xml"), 0), /JPEG|PNG/);
  assert.match(Attachments.checkFile(file("application/pdf"), 0), /JPEG|PNG/);
  assert.match(Attachments.checkFile(file("image/png", 0), 0), /empty/i);
  assert.match(Attachments.checkFile(file("image/png", Attachments.MAX_BYTES + 1), 0), /10 MB/);
  assert.equal(Attachments.checkFile(file("image/png", Attachments.MAX_BYTES), 0), null);
  assert.match(Attachments.checkFile(file("image/png"), 10), /at most 10/i);
  assert.equal(Attachments.checkFile(file("image/png"), 9), null);
});

test("imageFiles keeps only image files from a FileList-like or DataTransferItemList", () => {
  const list = [file("image/png", 1, "x"), file("text/plain", 1, "y"), file("image/jpeg", 1, "z")];
  assert.deepEqual(Attachments.imageFiles(list).map((f) => f.name), ["x", "z"]);
  assert.deepEqual(Attachments.imageFiles(null), []);
  assert.deepEqual(Attachments.imageFiles(undefined), []);
});

test("imageFiles reads files out of clipboard items", () => {
  const png = file("image/png", 1, "pasted");
  const items = [
    { kind: "string", type: "text/plain", getAsFile: () => null },
    { kind: "file", type: "image/png", getAsFile: () => png },
  ];
  assert.deepEqual(Attachments.imageFiles(items), [png]);
});

test("attachmentPath builds the API path", () => {
  assert.equal(Attachments.attachmentPath("t1", "a1"), "/todos/t1/attachments/a1");
  assert.equal(Attachments.attachmentPath("t1"), "/todos/t1/attachments");
});

test("uploadError maps statuses to plain messages", () => {
  assert.match(Attachments.uploadError(413), /10 MB/);
  assert.match(Attachments.uploadError(400, "at most 10 images per todo"), /at most 10/i);
  assert.match(Attachments.uploadError(404), /no longer exists/i);
  assert.match(Attachments.uploadError(0), /offline|connection/i);
  assert.match(Attachments.uploadError(500), /try again/i);
});

test("canUpload is false for todos the server doesn't know yet", () => {
  assert.equal(Attachments.canUpload({ todo_id: "tmp:abc" }), false);
  assert.equal(Attachments.canUpload({ todo_id: "5f1c" }), true);
});
