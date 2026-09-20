---
type: Feature
title: Image attachments
description: Images on todos, bytes in a private Cloud Storage bucket, served only through the API.
resource: app/main.py
tags: [attachments, storage, images]
timestamp: 2026-09-20T14:00:00Z
---
- **Limits:** ≤10 images per todo, 10 MB each; JPEG, PNG, GIF, WebP only. The server sniffs the leading bytes and ignores the client's `Content-Type`; SVG is refused (400 wrong type, 413 too big, 400 at the cap).
- **Metadata** is `Todo.attachments` `[{id, name, content_type, size}]` ([Todo](../data/todo.md)). It is only changed by the attachment routes (a `PATCH` cannot touch it), and each change bumps `version` and the rev like any content edit. Old docs default to `[]`.
- **Bytes** live in the private bucket `<project-id>-attachments` (`us-central1`, public access prevention on, uniform access, no CORS) at `todos/{todo_id}/{attachment_id}`. `app/blobstore.py` has `GcsStore` and an in-memory store; the bucket is chosen by the `ATTACHMENTS_BUCKET` env var. Unset locally = in-memory (lost on restart); unset on Cloud Run (`K_SERVICE`) = uploads fail with an error rather than lose data. Provision with `scripts/create-bucket.sh` ([deploy](../ops/deploy.md)).
- **Routes:** `POST/GET/DELETE /todos/{id}/attachments[/{aid}]` ([routes](../api/routes.md)). Upload writes the blob first, then appends the metadata in one transaction; a stale `If-Match`, a full todo, an idempotent replay, or a failed commit deletes the just-written blob (after a failure, only if the stored todo doesn't list it). Deletes remove the blob after commit; a crash in between is cleaned by the daily orphan sweep. Downloads are `nosniff`, `inline`, `Cache-Control: private, max-age=31536000, immutable`, and work for trashed todos.
- **Lifecycle:** soft delete keeps images (undelete restores them); the [archive](trash-archive.md) sweep deletes `todos/{id}/` for each archived todo; a [recurring](repeating-todos.md) clone starts with none.
- **Client:** `web/attachments.js` (pure helpers) and `web/attachments-ui.js` (the "Images" section of the todo viewer: picker, drag-drop, paste, lightbox). Images are fetched with the auth token and shown as blob URLs. Online only: nothing is queued in the outbox, a todo with a `tmp:` id can't take images, and the UI adopts the response's `attachments`/`version` and reports its rev via `engine.observeRev` ([sync](sync-model.md)).

Client memory: thumbnails/lightbox use blob URLs kept per page for the todo on screen only; other todos' URLs are revoked when a new section renders, and removing an attachment revokes its URL. There is no smaller server variant, so thumbnails still download the full image.
