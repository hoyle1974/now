# Image attachments on todos

Attach images to a todo, stored in a private Cloud Storage bucket, served only
through the authenticated API. Online-only; no offline queuing.

## Scope

In: images (JPEG, PNG, WebP, GIF), upload/view/delete, purge on archive.
Out (v1): other file types, offline upload queue, thumbnails, client-side
resize, server-side re-encode, HEIC, SVG.

## Bucket

- Name `your-gcp-project-id-attachments`, `us-central1`, Standard class.
- Uniform bucket-level access on; public access prevention enforced; no CORS
  (the browser never talks to GCS).
- Versioning off; GCS default 7-day soft delete left on as an undo.
- IAM: the Cloud Run runtime service account gets `roles/storage.objectAdmin`
  bound on this bucket only. No signing permission needed (no signed URLs).
- Provisioned by `scripts/create-bucket.sh`; Cloud Run reads `ATTACHMENTS_BUCKET`.
- Object key: `todos/{todo_id}/{attachment_id}` (uuid4 id).

## Data model

`Todo.attachments: list[Attachment]`, each `{id, name, content_type, size}`.
The todo document is the source of truth; the bucket holds bytes only. Metadata
changes go through the existing version / `If-Match` machinery. Max 10 per todo.

## API

All behind `require_user`; the widget token does not unlock these routes.

- `POST /todos/{id}/attachments` (multipart, one file)
  1. Reject > 10 MB.
  2. Sniff magic bytes; allow only JPEG/PNG/WebP/GIF; ignore client
     `Content-Type`. Store the sniffed type.
  3. Write the object.
  4. Append metadata to the todo in a transaction (409 on stale version, 400
     if already at 10).
  5. If step 4 fails, best-effort delete the object. Rare orphans accepted.
  Returns the updated todo.
- `GET /todos/{id}/attachments/{aid}` streams bytes with the sniffed
  `Content-Type`, `X-Content-Type-Options: nosniff`,
  `Content-Disposition: inline`,
  `Cache-Control: private, max-age=31536000, immutable`. 404 if the id is not
  in the todo's metadata.
- `DELETE /todos/{id}/attachments/{aid}` removes the metadata, then the object.
- Soft-deleting a todo keeps its attachments (undelete just works). The 30-day
  archive step deletes the `todos/{id}/` prefix.

## Blob store seam

`app/blobstore.py`: `put`, `get`, `delete`, `delete_prefix`. A GCS
implementation and an in-memory one for tests and local dev, selected by
whether `ATTACHMENTS_BUCKET` is set.

## Client

Attach via file picker, drag-drop and paste. Thumbnail strip in the todo detail
view (near the links UI in `web/fields-ui.js`); tap opens a lightbox. Images are
fetched through the auth-wrapped `fetch` and shown as blob URLs. Upload shows
progress and an error state. No offline queuing: attachments appear only after
the upload succeeds.

## Testing

Backend: pytest against the in-memory blob store (size cap, magic-byte
rejection incl. SVG and spoofed content-type, 10-attachment cap, stale version,
delete, purge on archive, auth required). Client: `node --test` for the pure
helpers. Manual: real bucket smoke test after `create-bucket.sh` and deploy.

## Open items

Client-side resize before upload is deferred; revisit if phone photos feel slow.
