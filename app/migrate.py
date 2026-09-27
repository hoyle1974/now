"""Move a subtree from one data partition to another: share, unshare, and dragging an
item into or out of a share (docs/okf/features/sharing.md).

Ids, versions and every field are kept, so an edit a device queued against the old
home still applies in the new one (routes/common.atomic finds it there). The move runs
in recorded steps; each is safe to repeat, so a run that dies half-way is finished by
resume_if_stale on a later read:

  frozen   the record is in {src}/meta/rev under `migrating`; every other write to src
           is refused (db.Frozen → 503 "migrating", which clients retry)
  blobs    attachment bytes copied to the destination prefix
  copied   documents copied (root placed at its destination), in batches of BATCH
  switched source documents deleted (sharing: the root's doc becomes the owner's
           mount), revisions bumped, share state set
  done     source blobs deleted, freeze cleared
"""
from __future__ import annotations

import datetime
from typing import Literal

from google.cloud import firestore  # type: ignore[attr-defined]

from app import blobstore, db, models, shares, tenant, types
from app.db_firestore_helpers import get_subtree_docs, todo_to_doc

Kind = Literal["share", "unshare", "move"]
STEPS = ("frozen", "blobs", "copied", "switched", "done")
MAX_NODES = 2000
BATCH = 200  # Firestore's limit is 500 writes per batch; same margin as the archive sweep
LEASE = datetime.timedelta(minutes=2)


class MigrationError(Exception):
    """A move that must not happen. detail: "crosses share boundary" (a calendar item or a
    mount would enter a share), "not eligible" (already shared, or not a user's item),
    "too large", "parent not found"."""
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


# How each MigrationError.detail answers over HTTP (the share and reparent routes).
HTTP_STATUS = {"crosses share boundary": 409, "not eligible": 400, "too large": 413, "parent not found": 404}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _todos(partition: str):
    return db.partition_ref(partition).collection("todos")


def _rev_ref(partition: str):
    return db.partition_ref(partition).collection("meta").document("rev")


def _is_share(partition: str) -> bool:
    return partition.startswith("shares/")


def _collect(src: str, root_id: str) -> list[dict]:
    """The root's doc, then every descendant (deleted ones too)."""
    snap = _todos(src).document(root_id).get()
    if not snap.exists:
        raise MigrationError("not eligible")
    return [snap.to_dict(), *get_subtree_docs(_todos(src), root_id)]


def _validate(kind: Kind, src: str, dst: str, nodes: list[dict], dst_parent: str | None) -> None:
    root = nodes[0]
    if kind == "share" and (_is_share(src) or not types.can_type(root.get("type"), "shareable")):
        raise MigrationError("not eligible")
    if kind != "unshare" and len(nodes) > MAX_NODES:  # a share must always be able to end
        raise MigrationError("too large")
    if _is_share(dst) and any(not types.can_type(n.get("type"), "shareable") for n in nodes):
        raise MigrationError("crosses share boundary")
    if kind == "move" and dst_parent is None and _is_share(dst):
        raise MigrationError("crosses share boundary")  # a share has exactly one top-level item
    if kind == "move" and dst_parent is not None:
        parent = _todos(dst).document(dst_parent).get()
        if not parent.exists or (parent.to_dict() or {}).get("deleted"):
            raise MigrationError("parent not found")


def _freeze(src: str, record: dict) -> None:
    ref = _rev_ref(src)

    @firestore.transactional
    def take(tx) -> None:
        snap = ref.get(transaction=tx)
        if snap.exists and (snap.to_dict() or {}).get("migrating"):
            raise db.Frozen()
        tx.set(ref, {"migrating": record}, merge=True)

    take(db.get_conn().transaction())


def _save_step(record: dict, step: str) -> None:
    record["step"] = step
    record["lease_until"] = (_now() + LEASE).isoformat()
    _rev_ref(record["src"]).update({"migrating.step": step, "migrating.lease_until": record["lease_until"]})


def migrate_subtree(src: str, root_id: str, dst: str, *, kind: Kind, dst_parent: str | None = None,
                    index: int | None = None, mode: str | None = None,
                    crash_after: str | None = None) -> None:
    """Move root_id and everything beneath it from partition src to dst.

    share:   dst is shares/{root_id}; a share doc (owner = the bound user, mode) is made;
             the root's place in src becomes the owner's mount.
    unshare: src is shares/{id}, dst the owner's partition; the root takes the owner's
             mount's place; the share becomes an "unshared" tombstone.
    move:    the root goes under dst_parent (None: top level) at index; siblings renumbered.
    crash_after (tests) raises after that step, to exercise resume_if_stale."""
    nodes = _collect(src, root_id)
    _validate(kind, src, dst, nodes, dst_parent)
    root = nodes[0]
    if kind == "unshare":
        mount = _todos(dst).document(root_id).get().to_dict() or {}
        place = (mount.get("parent_id"), mount.get("order_idx"))
    elif kind == "share":
        place = (None, 0)
    else:
        place = (dst_parent, index)
    record = {
        "kind": kind, "src": src, "dst": dst, "root_id": root_id, "mode": mode,
        "user": tenant.current(), "step": "frozen", "lease_until": (_now() + LEASE).isoformat(),
        "place": list(place), "root_was": [root.get("parent_id"), root.get("order_idx")],
        "ids": [n["todo_id"] for n in nodes],
        # "todo_id/attachment_id" (Firestore stores no arrays of arrays)
        "blobs": [f'{n["todo_id"]}/{a["id"]}' for n in nodes for a in n.get("attachments") or []],
    }
    _freeze(src, record)
    # What moves is read again now that nothing else can write: an item or image added
    # between the first read and the freeze moves too.
    try:
        nodes = _collect(src, root_id)
        _validate(kind, src, dst, nodes, dst_parent)
    except Exception:
        _rev_ref(src).update({"migrating": firestore.DELETE_FIELD})
        raise
    record["ids"] = [n["todo_id"] for n in nodes]
    record["blobs"] = [f'{n["todo_id"]}/{a["id"]}' for n in nodes for a in n.get("attachments") or []]
    _rev_ref(src).update({"migrating.ids": record["ids"], "migrating.blobs": record["blobs"]})
    if kind == "share":
        shares.put(shares.Share(id=root_id, owner=tenant.current(), mode=mode or "rw", state="migrating"))
    _run(record, crash_after)


def resume_if_stale(partition: str) -> bool:
    """Finish a migration out of `partition` whose run died (lease expired). True if one ran."""
    ref = _rev_ref(partition)
    now = _now()

    @firestore.transactional
    def claim(tx) -> dict | None:
        snap = ref.get(transaction=tx)
        record = (snap.to_dict() or {}).get("migrating") if snap.exists else None
        if not record or datetime.datetime.fromisoformat(record["lease_until"]) > now:
            return None
        record["lease_until"] = (now + LEASE).isoformat()
        tx.update(ref, {"migrating.lease_until": record["lease_until"]})
        return record

    record = claim(db.get_conn().transaction())
    if record is None:
        return False
    with tenant.as_user(record["user"]):
        _run(record)
    return True


def _run(record: dict, crash_after: str | None = None) -> None:
    token = db.migration_writes.set(True)
    try:
        if crash_after == record["step"]:
            raise RuntimeError("injected")
        for step, action in (("frozen", _copy_blobs), ("blobs", _copy_docs),
                             ("copied", _switch), ("switched", _finish)):
            if record["step"] != step:
                continue
            action(record)
            nxt = STEPS[STEPS.index(step) + 1]
            if nxt == "done":
                break
            _save_step(record, nxt)
            if crash_after == nxt:
                raise RuntimeError("injected")
    finally:
        db.migration_writes.reset(token)


def _blob_key(partition: str, pair: str) -> str:
    return f"{partition}/todos/{pair}"


def _copy_blobs(record: dict) -> None:
    store = blobstore.get_store()
    for pair in record["blobs"]:
        dst_key = _blob_key(record["dst"], pair)
        if not store.exists(dst_key):
            store.copy(_blob_key(record["src"], pair), dst_key)


def _batched(items: list, write) -> None:
    for start in range(0, len(items), BATCH):
        batch = db.get_conn().batch()
        for item in items[start:start + BATCH]:
            write(batch, item)
        batch.commit()


def _copy_docs(record: dict) -> None:
    """Copy from the source as it is now (it is frozen, so it is what was validated)."""
    src, dst, root_id = record["src"], record["dst"], record["root_id"]
    snaps = [_todos(src).document(i).get() for i in record["ids"]]
    found = [s.to_dict() for s in snaps if s.exists]
    parent, order = record["place"]
    for data in found:
        if data["todo_id"] == root_id:
            data["parent_id"], data["order_idx"] = parent, order
            if record["kind"] == "share":
                data["deleted"], data["deleted_at"] = False, None
    _batched(found, lambda b, data: b.set(_todos(dst).document(data["todo_id"]), data))


def _bump(partition: str) -> None:
    _rev_ref(partition).set({"value": firestore.Increment(1), "triggered_by": None}, merge=True)


def _switch(record: dict) -> None:
    src, dst, root_id, kind = record["src"], record["dst"], record["root_id"], record["kind"]
    gone = [i for i in record["ids"] if not (kind == "share" and i == root_id)]
    if kind == "share":
        parent, order = record["root_was"]
        mount = models.Todo(todo_id=models.TodoId(root_id), title="", type="mount", order_idx=order,
                            parent_id=None if parent is None else models.TodoId(parent))
        _todos(src).document(root_id).set(todo_to_doc(mount))
    if kind == "unshare":
        gone = list(record["ids"])  # the root came home over the owner's mount
    _batched(gone, lambda b, i: b.delete(_todos(src).document(i)))
    if kind == "move":
        _renumber(dst, record["place"][0], root_id, record["place"][1])
    _bump(src)
    _bump(dst)
    if kind == "share":
        # Written whole: a run that died before the share record was first written still ends right.
        shares.put(shares.Share(id=root_id, owner=record["user"], mode=record["mode"] or "rw", state="active"))
        shares.bump_meta_rev()
    elif kind == "unshare":
        share_id = src.split("/", 1)[1]
        db.get_conn().collection("shares").document(share_id).update(
            {"state": "unshared", "returned_to": dst.split("/", 1)[1], "updated_at": _now()})
        shares.bump_meta_rev()


def _renumber(partition: str, parent_id: str | None, moved_id: str, index: int | None) -> None:
    siblings = [s.to_dict() for s in _todos(partition).where("parent_id", "==", parent_id).stream()]
    others = sorted((d for d in siblings if d["todo_id"] != moved_id and not d.get("deleted")),
                    key=lambda d: (d.get("order_idx") if d.get("order_idx") is not None else 999999,
                                   d.get("create_date", ""), d["todo_id"]))
    ids = [d["todo_id"] for d in others]
    ids.insert(len(ids) if index is None else max(0, min(index, len(ids))), moved_id)
    old = {d["todo_id"]: d.get("order_idx") for d in siblings}
    changes = [(i, n) for n, i in enumerate(ids) if old.get(i) != n]
    _batched(changes, lambda b, c: b.update(_todos(partition).document(c[0]), {"order_idx": c[1]}))


def _finish(record: dict) -> None:
    store = blobstore.get_store()
    for pair in record["blobs"]:
        store.delete(_blob_key(record["src"], pair))
    _rev_ref(record["src"]).update({"migrating": firestore.DELETE_FIELD})
