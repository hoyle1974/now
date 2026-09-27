"""Build shares directly in the emulator for route tests (no migration involved)."""
from __future__ import annotations

from app import db, models, shares, tenant
from app.db_firestore_helpers import todo_to_doc

ROOT = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"


def make_share(owner: str, mode: str = "rw", members="all", state: str = "active",
               returned_to: str | None = None, mount_for: tuple[str, ...] = ()) -> dict:
    """shares/ROOT with a list root and one todo child; a mount at the root of each
    email in mount_for. Returns the ids."""
    shares.put(shares.Share(id=ROOT, owner=owner, members=members, mode=mode, state=state,
                            returned_to=returned_to))
    root = models.Todo(todo_id=models.TodoId(ROOT), title="Trip", type="list", order_idx=0)
    child = models.Todo(todo_id=models.TodoId(CHILD), title="Book hotel", parent_id=models.TodoId(ROOT), order_idx=0)
    with tenant.as_user(owner), tenant.as_partition(f"shares/{ROOT}"):
        db.run_atomic(None, lambda: (db.create_todo(root), db.create_todo(child), (200, None))[-1])
    for email in mount_for:
        add_mount(email)
    return {"root": ROOT, "child": CHILD}


def add_mount(email: str, parent_id: str | None = None, order_idx: int = 0, deleted: bool = False) -> None:
    mount = models.Todo(todo_id=models.TodoId(ROOT), title="", type="mount", order_idx=order_idx,
                        parent_id=None if parent_id is None else models.TodoId(parent_id), deleted=deleted)
    with tenant.as_user(email):
        db.run_atomic(None, lambda: (db.create_todo(mount), (200, None))[-1])
