# Firestore implementation of todo database
from __future__ import annotations
from app import models
from app import db_firestore_helpers
import contextvars
import datetime
import json
import uuid
from typing import Callable
from google.cloud import firestore

_client = None
_todos_collection = None

TXN_COLLECTION = "txn_log"
# One document holding a counter that every data-changing transaction bumps.
# Clients compare it with the value they last saw to learn that another window
# wrote, without downloading the whole tree.
REV_COLLECTION = "meta"
REV_DOC = "rev"

# Set while run_atomic is executing. Every read then joins the Firestore
# transaction and every write is buffered in it, so a request's version check,
# its writes and its txn_log record commit (or retry) together. Firestore
# requires all of a transaction's reads to come before its writes, which is
# why the functions below read everything first and hand back the updated
# todo instead of re-reading it afterwards.
_tx: contextvars.ContextVar = contextvars.ContextVar("firestore_tx", default=None)
# A one-element list set alongside _tx; flipped to True by the first todo write
# so run_atomic knows whether the revision counter must move.
_wrote: contextvars.ContextVar = contextvars.ContextVar("firestore_wrote", default=None)


def _get(target):
    tx = _tx.get()
    return target.get() if tx is None else target.get(transaction=tx)

def _set(ref, data: dict):
    tx = _tx.get()
    if tx is None:
        ref.set(data)
    else:
        _wrote.get()[0] = True
        tx.set(ref, data)

def _update(ref, data: dict):
    tx = _tx.get()
    if tx is None:
        ref.update(data)
    else:
        _wrote.get()[0] = True
        tx.update(ref, data)


def init(memory: bool = False):
    """Initialize Firestore connection"""
    global _client, _todos_collection
    _client = firestore.Client()
    _todos_collection = _client.collection("todos")
    print("firestore: initialized")

def get_conn():
    """Return Firestore client"""
    global _client
    return _client

def teardown():
    """Cleanup Firestore connection"""
    global _client, _todos_collection
    if _client is not None:
        _client.close()
    _client = None
    _todos_collection = None


def get_rev() -> int:
    """Current revision (0 before the first write). One document read."""
    snap = get_conn().collection(REV_COLLECTION).document(REV_DOC).get()
    return snap.to_dict().get("value", 0) if snap.exists else 0


def run_atomic(txn_id: str | None, fn: Callable[[], tuple[int, dict | None]]) -> tuple[int, dict | None, int, int]:
    """Run fn() in one Firestore transaction, at most once per txn_id.

    fn returns (status, body). The writes it makes, the txn_log record and the
    revision bump commit together. Returns (status, body, prev, rev): rev is the
    revision after this request (unchanged when nothing was written, e.g. a
    409) and prev is the revision the request started from: a client that last
    saw a lower number than prev knows someone else wrote in between. A retry
    with a known txn_id replays the stored (status, body, prev, rev) without
    running fn again. Exceptions (e.g. 404) abort the transaction and
    are not logged.
    """
    client = get_conn()
    log_ref = None if txn_id is None else client.collection(TXN_COLLECTION).document(txn_id)
    rev_ref = client.collection(REV_COLLECTION).document(REV_DOC)

    @firestore.transactional
    def run(tx):
        token = _tx.set(tx)
        wrote_token = _wrote.set([False])
        try:
            # All reads first: Firestore rejects a read after a write.
            if log_ref is not None:
                snap = log_ref.get(transaction=tx)
                if snap.exists:
                    logged = snap.to_dict()
                    raw = logged.get("response_json")
                    return (logged["status"], (None if raw is None else json.loads(raw)),
                            logged.get("prev_rev", 0), logged.get("rev", 0))
            rev_snap = rev_ref.get(transaction=tx)
            prev = rev_snap.to_dict().get("value", 0) if rev_snap.exists else 0
            rev = prev

            status, body = fn()

            if _wrote.get()[0]:
                rev += 1
                tx.set(rev_ref, {"value": rev})
            if log_ref is not None:
                tx.set(log_ref, {
                    "status": status,
                    "response_json": None if body is None else json.dumps(body),
                    "prev_rev": prev,
                    "rev": rev,
                    "created_at": datetime.datetime.now(datetime.timezone.utc),
                })
            return status, body, prev, rev
        finally:
            _wrote.reset(wrote_token)
            _tx.reset(token)

    return run(client.transaction())

def prune_txn_log(hours: int = 24) -> int:
    """Delete idempotency records older than a client's retry window."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    removed = 0
    for doc in get_conn().collection(TXN_COLLECTION).where("created_at", "<", cutoff).stream():
        doc.reference.delete()
        removed += 1
    return removed


def _child_docs(parent_id: str | None, include_deleted: bool = False) -> list[dict]:
    docs = [d.to_dict() for d in _get(_todos_collection.where("parent_id", "==", parent_id))]
    if include_deleted:
        return docs
    return [d for d in docs if not d.get("deleted", False)]

def _sorted_by_order(docs: list[dict]) -> list[dict]:
    # Ties (legacy docs without an index, or a restored todo whose slot was
    # reused) fall back to creation time so every reader agrees on the order.
    return sorted(docs, key=lambda d: (
        d.get("order_idx") if d.get("order_idx") is not None else 999999,
        d.get("create_date", ""), d["todo_id"]))

def _child_ids(parent_id: str, include_deleted: bool = False) -> list[models.TodoId]:
    docs = _sorted_by_order(_child_docs(parent_id, include_deleted))
    return [models.TodoId(uuid.UUID(d["todo_id"])) for d in docs]

def _next_order_idx(parent_id: str | None) -> int:
    docs = _child_docs(parent_id)
    return max([d.get("order_idx") if d.get("order_idx") is not None else -1 for d in docs] or [-1]) + 1


def create_todo(todo: models.Todo):
    """Create a new todo in Firestore"""
    global _todos_collection

    # Roots are ordered like any other sibling list, so a new todo goes last.
    if todo.order_idx is None:
        todo.order_idx = _next_order_idx(None if todo.parent_id is None else str(todo.parent_id))
    doc_data = db_firestore_helpers.todo_to_doc(todo)
    _set(_todos_collection.document(str(todo.todo_id)), doc_data)

def delete_todo(todo_id: models.TodoId):
    """Soft delete a todo and its subtree"""
    global _todos_collection

    descendant_ids = db_firestore_helpers.get_subtree_ids(
        _todos_collection, str(todo_id)
    )
    descendant_ids.insert(0, str(todo_id))

    for desc_id in descendant_ids:
        _todos_collection.document(desc_id).update({"deleted": True})

def reorder_todo(todo_id: models.TodoId, direction: str) -> models.Todo:
    """Move a todo up or down within its siblings (roots are siblings too).

    Normally this swaps the order_idx of just the two neighbours. Only if the
    indices are missing or duplicated (legacy docs) are the siblings compacted.
    Order isn't content: only the moved todo's version is bumped, so a
    neighbour's cached version stays valid.
    """
    global _todos_collection

    if direction not in ("up", "down"):
        raise Exception("direction must be 'up' or 'down'")

    moved_ref = _todos_collection.document(str(todo_id))
    moved_doc = _get(moved_ref)
    if not moved_doc.exists:
        raise Exception("Todo not found")

    moved_data = moved_doc.to_dict()
    siblings = _sorted_by_order(_child_docs(moved_data.get("parent_id")))
    if len(siblings) < 2:
        raise Exception("Cannot move: no siblings to swap with")

    current_pos = next((i for i, d in enumerate(siblings) if d["todo_id"] == str(todo_id)), None)
    if current_pos is None:
        raise Exception("Todo not in sibling list")

    new_pos = current_pos - 1 if direction == "up" else current_pos + 1
    if new_pos < 0:
        raise Exception("Already at top")
    if new_pos >= len(siblings):
        raise Exception("Already at bottom")

    moved = db_firestore_helpers.doc_to_todo(moved_data)
    moved.child_ids = _child_ids(str(todo_id))

    a, b = siblings[current_pos].get("order_idx"), siblings[new_pos].get("order_idx")
    if a is not None and b is not None and a != b:
        new_indices = {str(todo_id): b, siblings[new_pos]["todo_id"]: a}
    else:
        siblings.insert(new_pos, siblings.pop(current_pos))
        new_indices = {d["todo_id"]: i for i, d in enumerate(siblings)}

    for sibling_id, idx in new_indices.items():
        if sibling_id == str(todo_id):
            moved.order_idx = idx
            moved.version += 1
            _update(moved_ref, {"order_idx": idx, "version": moved.version})
        else:
            current = next(d for d in siblings if d["todo_id"] == sibling_id).get("order_idx")
            if current != idx:
                _update(_todos_collection.document(sibling_id), {"order_idx": idx})
    return moved

def undelete_todo(todo_id: models.TodoId) -> tuple[models.Todo, list[tuple[str, int]]]:
    """Restore a soft-deleted todo.

    Deleting only flags the todo itself; its descendants keep their own state
    and just become unreachable. So undo flips that one flag back. Touching the
    descendants would resurrect children the user had deleted earlier.

    Returns the restored todo and [(todo_id, version)] for the row it touched.
    """
    global _todos_collection

    root_ref = _todos_collection.document(str(todo_id))
    root_data = _get(root_ref).to_dict()

    order_idx = root_data.get("order_idx")
    if order_idx is None:
        order_idx = _next_order_idx(root_data.get("parent_id"))

    child_ids = _child_ids(str(todo_id))  # reads must precede the write

    version = root_data.get("version", 1) + 1
    fields = {"deleted": False, "version": version, "order_idx": order_idx}
    _update(root_ref, fields)

    restored = db_firestore_helpers.doc_to_todo({**root_data, **fields})
    restored.child_ids = child_ids
    return restored, [(str(todo_id), version)]

def update_todo(todo: models.Todo, bump_version: bool = True):
    """Update a todo and bump its version in place. Done state is per-todo; it
    never cascades to children. View state (collapsed) passes bump_version=False
    so it never invalidates another window's cached version."""
    global _todos_collection

    if bump_version:
        todo.version += 1
    doc_data = db_firestore_helpers.todo_to_doc(todo)
    _update(_todos_collection.document(str(todo.todo_id)), doc_data)

def update_parent_id(todo: models.Todo, parent_id: models.TodoId | None) -> models.Todo | None:
    """Move a todo to a different parent"""
    global _todos_collection

    if parent_id is not None and not _get(_todos_collection.document(str(parent_id))).exists:
        return None

    order_idx = todo.order_idx
    if parent_id and order_idx is None:
        order_idx = _next_order_idx(str(parent_id))

    todo.version += 1
    _update(_todos_collection.document(str(todo.todo_id)), {
        "parent_id": None if parent_id is None else str(parent_id),
        "order_idx": order_idx,
        "version": todo.version,
    })

    todo.parent_id = parent_id
    todo.order_idx = order_idx
    return todo

class ReparentError(Exception):
    """Raised for a move that can't be done: "missing" parent or a "cycle"."""
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def reparent_todo(todo: models.Todo, parent_id: models.TodoId | None, index: int | None) -> models.Todo:
    """Move a todo under another parent (or to the top level) at a position.

    index is the position among the new siblings (None or past the end means
    last). The new siblings are renumbered 0..n so the order is exact; only the
    moved todo's version is bumped (order isn't content, as in reorder_todo).
    Moving within the same parent is just a reorder to that index.
    Raises ReparentError("missing") for an unknown/deleted parent and
    ReparentError("cycle") for a move into the todo's own subtree.
    """
    global _todos_collection

    new_parent = None if parent_id is None else str(parent_id)
    moved_id = str(todo.todo_id)

    # All reads first: Firestore rejects a read after a write.
    if new_parent is not None:
        # Walk up from the new parent: meeting the moved todo means a cycle.
        seen = set()
        cursor = new_parent
        while cursor is not None:
            if cursor == moved_id:
                raise ReparentError("cycle")
            if cursor in seen:
                break
            seen.add(cursor)
            snap = _get(_todos_collection.document(cursor))
            if not snap.exists or snap.to_dict().get("deleted", False):
                raise ReparentError("missing")
            cursor = snap.to_dict().get("parent_id")

    siblings = [d for d in _sorted_by_order(_child_docs(new_parent)) if d["todo_id"] != moved_id]
    position = len(siblings) if index is None else max(0, min(index, len(siblings)))
    ids = [d["todo_id"] for d in siblings]
    ids.insert(position, moved_id)
    old_idx = {d["todo_id"]: d.get("order_idx") for d in siblings}

    todo.version += 1
    _update(_todos_collection.document(moved_id), {
        "parent_id": new_parent, "order_idx": position, "version": todo.version})
    for i, sid in enumerate(ids):
        if sid != moved_id and old_idx.get(sid) != i:
            _update(_todos_collection.document(sid), {"order_idx": i})

    todo.parent_id = parent_id
    todo.order_idx = position
    return todo

def _doc_to_todo_with_children(data: dict, include_deleted_children: bool = False) -> models.Todo:
    todo = db_firestore_helpers.doc_to_todo(data)
    todo.child_ids = _child_ids(str(todo.todo_id), include_deleted_children)
    return todo

def get_root_todos() -> list[models.Todo]:
    """Get all root-level todos (parent_id is None), oldest first"""
    global _todos_collection

    docs = _get(_todos_collection.where("parent_id", "==", None))

    todos = [
        _doc_to_todo_with_children(doc.to_dict())
        for doc in docs
        if not doc.to_dict().get("deleted", False)
    ]

    # Roots have no order_idx, and Firestore returns them by random document
    # id; creation time keeps new todos where the optimistic UI put them.
    todos.sort(key=_root_sort_key)

    return todos

def _root_sort_key(t: models.Todo):
    return (t.order_idx if t.order_idx is not None else 999999, t.create_date, str(t.todo_id))

def get_tree() -> tuple[list[models.Todo], dict[str, models.Todo]]:
    """The whole live tree from one collection read: (roots, todosById).

    Only todos reachable from a root are returned, so the children of a deleted
    todo stay hidden. child_ids come back in sibling order.
    """
    live: dict[str, models.Todo] = {}
    for doc in _todos_collection.stream():
        data = doc.to_dict()
        if not data.get("deleted", False):
            live[data["todo_id"]] = db_firestore_helpers.doc_to_todo(data)

    children: dict[str | None, list[models.Todo]] = {}
    for todo in live.values():
        children.setdefault(None if todo.parent_id is None else str(todo.parent_id), []).append(todo)
    for parent_id, kids in children.items():
        kids.sort(key=_root_sort_key)
        if parent_id is not None and parent_id in live:
            live[parent_id].child_ids = [k.todo_id for k in kids]

    roots = children.get(None, [])
    reachable: dict[str, models.Todo] = {}
    pending = list(roots)
    while pending:
        todo = pending.pop()
        reachable[str(todo.todo_id)] = todo
        pending.extend(children.get(str(todo.todo_id), []))
    return roots, reachable

def get_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a single todo by ID (excludes soft-deleted)"""
    global _todos_collection

    doc = _get(_todos_collection.document(str(todo_id)))
    if not doc.exists:
        return None

    data = doc.to_dict()
    if data.get("deleted", False):
        return None

    return _doc_to_todo_with_children(data)

def get_deleted_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a single todo by ID regardless of deleted status"""
    global _todos_collection

    doc = _get(_todos_collection.document(str(todo_id)))
    if not doc.exists:
        return None

    return _doc_to_todo_with_children(doc.to_dict(), include_deleted_children=True)

def split_into_children(todo: models.Todo, descriptions: list[str], due_date=None) -> tuple[models.Todo, list[tuple[str, int]]]:
    """Create child todos from descriptions.

    Returns the parent (child_ids and version updated) and the affected
    (todo_id, version) list: the parent first, then each new child in order.
    """
    global _todos_collection

    next_order = _next_order_idx(str(todo.todo_id))

    todo.version += 1
    affected = [(str(todo.todo_id), todo.version)]
    new_ids = []
    for description in descriptions:
        child_todo = models.Todo(
            title=description,
            parent_id=todo.todo_id,
            order_idx=next_order,
            due_date=due_date
        )
        _set(_todos_collection.document(str(child_todo.todo_id)),
             db_firestore_helpers.todo_to_doc(child_todo))
        new_ids.append(child_todo.todo_id)
        affected.append((str(child_todo.todo_id), child_todo.version))
        next_order += 1

    _update(_todos_collection.document(str(todo.todo_id)), {"version": todo.version})
    todo.child_ids = list(todo.child_ids) + new_ids
    return todo, affected
