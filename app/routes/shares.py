"""Sharing an item with everyone on this deployment (docs/okf/features/sharing.md)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app import auth, db, migrate, models, shares, tenant

router = APIRouter()

_STATUS = {"crosses share boundary": 409, "not eligible": 400, "too large": 413}


def _enabled() -> None:
    if not auth.sharing_enabled():
        raise HTTPException(404, "Not Found")


def _own(todo_id: uuid.UUID) -> models.Todo:
    """The item in the caller's own list (a share's place there is its mount)."""
    if shares.bound() is not None:
        raise HTTPException(400, "send share changes without X-Share")
    todo = db.get_todo(models.TodoId(todo_id))
    if todo is None:
        raise HTTPException(404, "todo not found")
    return todo


def _view(share: shares.Share) -> dict:
    return {"id": share.id, "owner": share.owner, "mode": share.mode, "state": share.state}


@router.put("/todos/{todo_id}/share", response_model=None)
def share_todo(todo_id: uuid.UUID, body: models.ShareRequest) -> dict:
    """Share an item (and everything beneath it) with everyone, or change a share's mode.
    Sharing moves its data into shares/{id}; the item's place in your list becomes a mount."""
    _enabled()
    todo = _own(todo_id)
    if todo.type == "mount":
        share = shares.get(str(todo_id))
        if share is None or share.state != "active":
            raise HTTPException(404, "todo not found")
        if share.owner != tenant.current():
            raise HTTPException(403, "owner only")
        if share.mode != body.mode:
            shares.set_mode(share.id, body.mode)
        return {"share": _view(shares.get(share.id))}
    try:
        migrate.migrate_subtree(tenant.partition(), str(todo_id), f"{shares.SHARES}/{todo_id}",
                                kind="share", mode=body.mode)
    except migrate.MigrationError as e:
        raise HTTPException(_STATUS.get(e.detail, 400), e.detail) from e
    return {"share": _view(shares.get(str(todo_id)))}


@router.delete("/todos/{todo_id}/share", response_model=None)
def unshare_todo(todo_id: uuid.UUID) -> dict:
    """Stop sharing: the items move back into the owner's list where their mount was;
    everyone else's mount disappears."""
    _enabled()
    todo = _own(todo_id)
    share = shares.get(str(todo_id)) if todo.type == "mount" else None
    if share is None or share.state != "active":
        raise HTTPException(404, "todo not found")
    if share.owner != tenant.current():
        raise HTTPException(403, "owner only")
    migrate.migrate_subtree(share.partition(), share.id, tenant.partition(), kind="unshare")
    return {"share": _view(shares.get(share.id))}


@router.get("/shares", response_model=None)
def list_shares() -> dict:
    """"Shared with me": every live share the caller can see, and whether it is in their list."""
    _enabled()
    email = tenant.current()
    mine = {m["todo_id"]: m for m in shares.mounts(email)}
    items = []
    for share in shares.active_shares():
        if not shares.is_member(share, email):
            continue
        with tenant.as_partition(share.partition()):
            root = db.get_deleted_todo(models.TodoId(share.id))
        if root is None or root.deleted:
            continue
        mount = mine.get(share.id)
        items.append({"id": share.id, "title": root.title, "owner": share.owner, "mode": share.mode,
                      "mounted": mount is not None and not mount.get("deleted"),
                      "removed": mount is not None and bool(mount.get("deleted"))})
    return {"items": items}
