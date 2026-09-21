"""Image attachments on a todo."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Header, HTTPException, Response, UploadFile
from fastapi.encoders import jsonable_encoder

from app import attachments, blobstore, db, models
from app.routes.common import apply, reply

router = APIRouter()

@router.post("/todos/{todo_id}/attachments", response_model=None)
def add_attachment(todo_id: uuid.UUID, file: UploadFile = File(...),
                   x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    # (Oversized uploads announcing their length are already refused by _limit_upload_size.)
    data = file.file.read(models.MAX_ATTACHMENT_BYTES + 1)
    if len(data) > models.MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "image too large (10 MB max)")
    content_type = attachments.sniff_image_type(data)
    if content_type is None:
        raise HTTPException(400, "only JPEG, PNG, GIF and WebP images are allowed")
    if db.get_todo(models.TodoId(todo_id)) is None:
        raise HTTPException(404, "todo not found")

    meta = models.Attachment(id=uuid.uuid4().hex, name=attachments.clean_name(file.filename),
                             content_type=content_type, size=len(data))
    key = blobstore.key_for(str(todo_id), meta.id)
    blobstore.get_store().put(key, data, content_type)

    def action(todo: models.Todo) -> dict:
        if len(todo.attachments) >= models.MAX_ATTACHMENTS:
            raise HTTPException(400, f"at most {models.MAX_ATTACHMENTS} images per todo")
        todo.attachments = [*todo.attachments, meta]
        db.update_todo(todo)
        return jsonable_encoder(todo)

    def referenced(body: dict | None) -> bool:
        return body is not None and any(a["id"] == meta.id for a in body.get("attachments", []))

    try:
        result = db.run_atomic(x_txn_id, lambda: apply(todo_id, if_match, action))
    except BaseException:
        # A failed attempt may have set the todo up in a transaction that never
        # committed: keep the blob only if the stored todo really lists it.
        stored = db.get_deleted_todo(models.TodoId(todo_id))
        if stored is None or not any(a.id == meta.id for a in stored.attachments):
            blobstore.get_store().delete(key)
        raise
    if not (result[0] == 200 and referenced(result[1])):
        # A 409, or an idempotent replay of another response, leaves the blob unreferenced.
        blobstore.get_store().delete(key)
    return reply(*result)

@router.get("/todos/{todo_id}/attachments/{attachment_id}", response_model=None)
def get_attachment(todo_id: uuid.UUID, attachment_id: str) -> Response:
    todo = db.get_deleted_todo(models.TodoId(todo_id))  # trashed todos keep their images
    if todo is None:
        raise HTTPException(404, "todo not found")
    if not any(a.id == attachment_id for a in todo.attachments):
        raise HTTPException(404, "attachment not found")
    stored = blobstore.get_store().get(blobstore.key_for(str(todo_id), attachment_id))
    if stored is None:
        raise HTTPException(404, "attachment not found")
    data, content_type = stored
    return Response(data, media_type=content_type, headers={
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
        # An attachment's bytes never change, so the browser may keep them forever.
        "Cache-Control": "private, max-age=31536000, immutable",
    })

@router.delete("/todos/{todo_id}/attachments/{attachment_id}", response_model=None)
def delete_attachment(todo_id: uuid.UUID, attachment_id: str,
                      x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    def action(todo: models.Todo) -> dict:
        if not any(a.id == attachment_id for a in todo.attachments):
            raise HTTPException(404, "attachment not found")
        todo.attachments = [a for a in todo.attachments if a.id != attachment_id]
        db.update_todo(todo)
        return jsonable_encoder(todo)

    result = db.run_atomic(x_txn_id, lambda: apply(todo_id, if_match, action))
    if result[0] == 200:
        blobstore.get_store().delete(blobstore.key_for(str(todo_id), attachment_id))
    return reply(*result)
