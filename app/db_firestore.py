# Firestore implementation of todo database
from __future__ import annotations

import contextlib
import contextvars
import copy
import datetime
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from google.cloud import firestore  # type: ignore[attr-defined]

from app import blobstore, db_firestore_helpers, models, recurrence, types

log = logging.getLogger(__name__)



class _State:
    """Per-process Firestore state. init() fills it, teardown() clears it."""
    def __init__(self) -> None:
        self.client: Any = None
        self.todos: Any = None  # the "todos" collection; None until init()
        # (rev, roots, todosById) of the last full tree read. A tree read costs one
        # document read per todo, so it is reused for as long as the revision counter
        # hasn't moved (every write to a todo bumps it in run_atomic).
        self.tree_cache: tuple | None = None
        self.archive_checked: float | None = None  # time.monotonic() of the last archive attempt

    def reset(self) -> None:
        self.tree_cache = None
        self.archive_checked = None


_state = _State()

# Todos deleted for ARCHIVE_AFTER_DAYS move (subtree and all) out of "todos", so
# the live collection, which every tree read scans, stays small.
ARCHIVE_COLLECTION = "todos_archive"
ARCHIVE_AFTER_DAYS = 30
# In REV_COLLECTION: {"last_success": iso, "lease_until": iso}, so instances don't repeat the sweep.
ARCHIVE_DOC = "archive"
_ARCHIVE_CHECK_SECONDS = 24 * 3600
_ARCHIVE_RETRY_SECONDS = 15 * 60  # in-process backoff after a failed run
_ARCHIVE_LEASE = datetime.timedelta(minutes=15)  # how long a run may hold the claim
_archive_lock = threading.Lock()  # one sweep at a time per process

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


def init():
    """Initialize Firestore connection"""
    _state.reset()
    _state.client = firestore.Client()
    _state.todos = _state.client.collection("todos")
    log.info("firestore: initialized")

def get_conn():
    """Return Firestore client"""
    return _state.client

def teardown():
    """Cleanup Firestore connection"""
    _state.reset()
    if _state.client is not None:
        _state.client.close()
    _state.client = None
    _state.todos = None


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


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
                    "created_at": datetime.datetime.now(datetime.UTC),
                })
            return status, body, prev, rev
        finally:
            _wrote.reset(wrote_token)
            _tx.reset(token)

    return run(client.transaction())

def prune_txn_log(hours: int = 24 * 30) -> int:
    """Delete idempotency records older than a client's retry window.

    A phone can sit offline with a sent-but-unacked create/split in its outbox
    (same txn_id kept in IndexedDB) for days; if the record were gone by the
    time it reconnects, the replay would run again and duplicate todos. 30 days
    is far past any realistic offline stretch and the records are tiny."""
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)
    removed = 0
    for doc in get_conn().collection(TXN_COLLECTION).where("created_at", "<", cutoff).stream():
        doc.reference.delete()
        removed += 1
    return removed


def _child_docs(parent_id: str | None, include_deleted: bool = False) -> list[dict]:
    docs = [d.to_dict() for d in _get(_state.todos.where("parent_id", "==", parent_id))]
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
    return max((d["order_idx"] if d.get("order_idx") is not None else -1 for d in docs), default=-1) + 1


def create_todo(todo: models.Todo):
    """Create a new todo in Firestore"""

    # Roots are ordered like any other sibling list, so a new todo goes last.
    if todo.order_idx is None:
        todo.order_idx = _next_order_idx(None if todo.parent_id is None else str(todo.parent_id))
    doc_data = db_firestore_helpers.todo_to_doc(todo)
    _set(_state.todos.document(str(todo.todo_id)), doc_data)

class MoveError(Exception):
    """A move up/down that deliberately can't happen: kind is "missing" (no such
    todo) or "blocked" (bad direction, no siblings, already at the end). Anything
    else raised while moving is an unexpected failure and must not look like one."""
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def reorder_todo(todo_id: models.TodoId, direction: str) -> models.Todo:
    """Move a todo up or down within its siblings (roots are siblings too).

    Normally this swaps the order_idx of just the two neighbours. Only if the
    indices are missing or duplicated (legacy docs) are the siblings compacted.
    Order isn't content: only the moved todo's version is bumped, so a
    neighbour's cached version stays valid.
    """

    if direction not in ("up", "down"):
        raise MoveError("blocked", "direction must be 'up' or 'down'")

    moved_ref = _state.todos.document(str(todo_id))
    moved_doc = _get(moved_ref)
    if not moved_doc.exists:
        raise MoveError("missing", "Todo not found")

    moved_data = moved_doc.to_dict()
    siblings = _sorted_by_order(_child_docs(moved_data.get("parent_id")))
    if len(siblings) < 2:
        raise MoveError("blocked", "no siblings to swap with")

    current_pos = next((i for i, d in enumerate(siblings) if d["todo_id"] == str(todo_id)), None)
    if current_pos is None:
        raise MoveError("blocked", "Todo not in sibling list")

    new_pos = current_pos - 1 if direction == "up" else current_pos + 1
    if new_pos < 0:
        raise MoveError("blocked", "Already at top")
    if new_pos >= len(siblings):
        raise MoveError("blocked", "Already at bottom")

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
                _update(_state.todos.document(sibling_id), {"order_idx": idx})
    return moved

def undelete_todo(todo_id: models.TodoId) -> tuple[models.Todo, list[tuple[str, int]]]:
    """Restore a soft-deleted todo.

    Deleting only flags the todo itself; its descendants keep their own state
    and just become unreachable. So undo flips that one flag back. Touching the
    descendants would resurrect children the user had deleted earlier.

    Returns the restored todo and [(todo_id, version)] for the row it touched.
    """

    root_ref = _state.todos.document(str(todo_id))
    root_data = _get(root_ref).to_dict()

    # If any ancestor is deleted (or gone) the restored todo would stay
    # invisible, so it goes to the top level instead.
    parent_id = root_data.get("parent_id")
    cursor, seen = parent_id, set()
    while cursor is not None:
        snap = _get(_state.todos.document(cursor))
        if not snap.exists or snap.to_dict().get("deleted", False) or cursor in seen:
            parent_id = None
            break
        seen.add(cursor)
        cursor = snap.to_dict().get("parent_id")

    order_idx = root_data.get("order_idx")
    if order_idx is None or parent_id != root_data.get("parent_id"):
        order_idx = _next_order_idx(parent_id)

    child_ids = _child_ids(str(todo_id))  # reads must precede the write

    version = root_data.get("version", 1) + 1
    fields = {"deleted": False, "deleted_at": None, "version": version, "order_idx": order_idx,
              "parent_id": parent_id}
    _update(root_ref, fields)

    restored = db_firestore_helpers.doc_to_todo({**root_data, **fields})
    restored.child_ids = child_ids
    return restored, [(str(todo_id), version)]

def _stream_all():
    tx = _tx.get()
    return _state.todos.stream() if tx is None else _state.todos.stream(transaction=tx)

def clear_completed() -> list[tuple[str, int]]:
    """Soft-delete every done todo whose whole live subtree is done.

    Only the topmost such todo of each subtree is flagged (like a normal
    delete): its descendants stay unflagged and hidden, so undoing it brings
    the subtree back intact. Done todos with an unfinished descendant are kept.
    Returns [(todo_id, new_version)].
    """
    live: dict[str, dict] = {}
    for doc in _stream_all():
        data = doc.to_dict()
        if not data.get("deleted", False):
            live[data["todo_id"]] = data
    children: dict[str | None, list[str]] = {}
    for tid, data in live.items():
        children.setdefault(data.get("parent_id"), []).append(tid)

    memo: dict[str, tuple[bool, bool]] = {}
    def check(tid: str) -> tuple[bool, bool]:
        """(everything beneath is done, a todo is here or beneath). A container's own
        `done` means nothing, so only the todos in it decide."""
        if tid not in memo:
            memo[tid] = (False, False)  # cycle guard
            data = live[tid]
            kids = [check(c) for c in children.get(tid, [])]
            has_state = types.can_type(data.get("type"), "hasCheckbox")
            memo[tid] = (all(k[0] for k in kids) and (data.get("done", False) or not has_state),
                         has_state or any(k[1] for k in kids))
        return memo[tid]

    cleared = []
    pending = list(children.get(None, []))
    while pending:
        tid = pending.pop()
        all_done, has_todo = check(tid)
        if all_done and has_todo:
            data = live[tid]
            version = data.get("version", 1) + 1
            _update(_state.todos.document(tid),
                    {"deleted": True, "deleted_at": _now_utc().isoformat(), "version": version})
            cleared.append((tid, version))
        else:
            pending.extend(children.get(tid, []))
    return cleared

def get_trash(limit: int = 200) -> list[models.Todo]:
    """Soft-deleted todos, newest created first (no delete timestamp is kept)."""
    items = [db_firestore_helpers.doc_to_todo(d.to_dict())
             for d in _state.todos.where("deleted", "==", True).stream()]
    items.sort(key=lambda t: (t.create_date, str(t.todo_id)), reverse=True)
    return items[:limit]

def update_todo(todo: models.Todo, bump_version: bool = True):
    """Update a todo and bump its version in place. Done state is per-todo; it
    never cascades to children. View state (collapsed) passes bump_version=False
    so it never invalidates another window's cached version."""

    if bump_version:
        todo.version += 1
    if not todo.deleted:
        todo.deleted_at = None
    elif todo.deleted_at is None:
        todo.deleted_at = _now_utc()
    doc_data = db_firestore_helpers.todo_to_doc(todo)
    _update(_state.todos.document(str(todo.todo_id)), doc_data)

def spawn_next_occurrence(todo: models.Todo, today: datetime.date) -> models.Todo:
    """Create the next occurrence of a repeating todo and mark the original as spawned.

    The copy is a sibling placed right after the original. It takes the next
    due date (see app/recurrence.py) and brings the original's live subtree
    along, every todo open again, each dated subtask shifted by the same amount.
    Deleted subtasks are left behind. Returns the copy's root.
    """

    original_ref = _state.todos.document(str(todo.todo_id))
    parent = None if todo.parent_id is None else str(todo.parent_id)

    # All reads first: Firestore rejects a read after a write.
    def live_children(doc_id: str) -> list[dict]:
        return _sorted_by_order(_child_docs(doc_id))

    tree: dict[str, list[dict]] = {}
    pending = [str(todo.todo_id)]
    while pending:
        node = pending.pop()
        tree[node] = live_children(node)
        pending.extend(d["todo_id"] for d in tree[node])
    siblings = _sorted_by_order(_child_docs(parent))

    assert todo.repeat is not None  # callers check before spawning
    new_due = recurrence.next_due(todo.due_date, todo.repeat, today)
    shift = None if todo.due_date is None else new_due - todo.due_date

    def clone(doc: dict, new_parent: models.TodoId | None, due: datetime.datetime | None) -> models.Todo:
        copy = db_firestore_helpers.doc_to_todo(doc)
        copy.todo_id = models.TodoId(uuid.uuid4())
        copy.parent_id = new_parent
        copy.done = False
        copy.deleted = False
        copy.create_date = models.utc_now()
        copy.due_date = due
        copy.spawned_id = None
        copy.version = 1
        copy.attachments = []  # the images belong to the original occurrence
        return copy

    copies: list[models.Todo] = []

    def clone_children(old_id: str, new_id: models.TodoId) -> None:
        for child in tree[old_id]:
            child_due = child_due_date(child)
            copy = clone(child, new_id, child_due)
            copies.append(copy)
            clone_children(child["todo_id"], copy.todo_id)

    def child_due_date(doc: dict) -> datetime.datetime | None:
        if doc.get("due_date") is None:
            return None
        due = datetime.datetime.fromisoformat(doc["due_date"])
        return due + shift if shift is not None else due

    original_doc = _get(original_ref).to_dict()
    root = clone(original_doc, todo.parent_id, new_due)

    # Slot the copy in right after the original and renumber the siblings.
    ids = [d["todo_id"] for d in siblings]
    at = ids.index(str(todo.todo_id)) + 1 if str(todo.todo_id) in ids else len(ids)
    ids.insert(at, str(root.todo_id))
    root.order_idx = at
    copies.insert(0, root)
    clone_children(str(todo.todo_id), root.todo_id)

    old_idx = {d["todo_id"]: d.get("order_idx") for d in siblings}
    for i, sid in enumerate(ids):
        if sid != str(root.todo_id) and old_idx.get(sid) != i:
            _update(_state.todos.document(sid), {"order_idx": i})
    for spawned in copies:
        _set(_state.todos.document(str(spawned.todo_id)), db_firestore_helpers.todo_to_doc(spawned))

    todo.spawned_id = root.todo_id
    todo.version += 1
    _update(original_ref, {"spawned_id": str(root.todo_id), "version": todo.version})
    return root


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
            snap = _get(_state.todos.document(cursor))
            if not snap.exists or snap.to_dict().get("deleted", False):
                raise ReparentError("missing")
            cursor = snap.to_dict().get("parent_id")

    siblings = [d for d in _sorted_by_order(_child_docs(new_parent)) if d["todo_id"] != moved_id]
    position = len(siblings) if index is None else max(0, min(index, len(siblings)))
    ids = [d["todo_id"] for d in siblings]
    ids.insert(position, moved_id)
    old_idx = {d["todo_id"]: d.get("order_idx") for d in siblings}

    todo.version += 1
    _update(_state.todos.document(moved_id), {
        "parent_id": new_parent, "order_idx": position, "version": todo.version})
    for i, sid in enumerate(ids):
        if sid != moved_id and old_idx.get(sid) != i:
            _update(_state.todos.document(sid), {"order_idx": i})

    todo.parent_id = parent_id
    todo.order_idx = position
    return todo

def _doc_to_todo_with_children(data: dict, include_deleted_children: bool = False) -> models.Todo:
    todo = db_firestore_helpers.doc_to_todo(data)
    todo.child_ids = _child_ids(str(todo.todo_id), include_deleted_children)
    return todo

def get_root_todos() -> list[models.Todo]:
    """Get all root-level todos (parent_id is None), oldest first"""

    docs = _get(_state.todos.where("parent_id", "==", None))

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

def get_tree(rev: int | None = None) -> tuple[list[models.Todo], dict[str, models.Todo]]:
    """The whole live tree from one collection read: (roots, todosById).

    Only todos reachable from a root are returned, so the children of a deleted
    todo stay hidden. child_ids come back in sibling order.

    rev is the revision the caller already read (read here if omitted). It is
    taken before the collection is, so the cache can only be keyed older than
    its contents: a write in between costs one extra reload, never a stale hit.
    Callers get their own copy, so they may modify what they receive.
    """
    if rev is None:
        rev = get_rev()
    if _state.tree_cache is not None and _state.tree_cache[0] == rev:
        return copy.deepcopy(_state.tree_cache[1:])
    roots, reachable = _read_tree()
    _state.tree_cache = (rev, roots, reachable)
    return copy.deepcopy((roots, reachable))

def _read_tree() -> tuple[list[models.Todo], dict[str, models.Todo]]:
    live: dict[str, models.Todo] = {}
    for doc in _state.todos.stream():
        data = doc.to_dict()
        if not data.get("deleted", False):
            live[data["todo_id"]] = db_firestore_helpers.doc_to_todo(data)
    # Derived flag. Ids of missing/deleted todos are simply ignored.
    for todo in live.values():
        todo.blocked = any(str(b) in live and not live[str(b)].done and types.can(live[str(b)], "hasCheckbox")
                           for b in todo.blocked_by)

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

    doc = _get(_state.todos.document(str(todo_id)))
    if not doc.exists:
        return None

    data = doc.to_dict()
    if data.get("deleted", False):
        return None

    return _doc_to_todo_with_children(data)

def get_deleted_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a single todo by ID regardless of deleted status"""

    doc = _get(_state.todos.document(str(todo_id)))
    if not doc.exists:
        return None

    return _doc_to_todo_with_children(doc.to_dict(), include_deleted_children=True)

def split_into_children(todo: models.Todo, descriptions: list[str],
                        due_date=None) -> tuple[models.Todo, list[tuple[str, int]]]:
    """Create child todos from descriptions.

    Returns the parent (child_ids and version updated) and the affected
    (todo_id, version) list: the parent first, then each new child in order.
    """

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
        _set(_state.todos.document(str(child_todo.todo_id)),
             db_firestore_helpers.todo_to_doc(child_todo))
        new_ids.append(child_todo.todo_id)
        affected.append((str(child_todo.todo_id), child_todo.version))
        next_order += 1

    _update(_state.todos.document(str(todo.todo_id)), {"version": todo.version})
    todo.child_ids = list(todo.child_ids) + new_ids
    return todo, affected


def get_links_graph_docs(todo_ids: list[str]) -> dict[str, dict | None]:
    """Raw docs (deleted or not) for the given ids; None where the id doesn't exist."""
    return {i: (lambda s: s.to_dict() if s.exists else None)(_get(_state.todos.document(i)))
            for i in todo_ids}

def is_ancestor(ancestor_id: str, todo_id: str) -> bool:
    """True if ancestor_id is somewhere above todo_id in the tree (deleted included)."""
    seen: set[str] = set()
    cur: str | None = todo_id
    while cur and cur not in seen:
        seen.add(cur)
        doc = get_links_graph_docs([cur])[cur]
        cur = (doc or {}).get("parent_id")
        if cur == ancestor_id:
            return True
    return False

def blocked_by_would_cycle(todo_id: str, new_blockers: list[str]) -> bool:
    """True if making todo_id blocked by new_blockers closes a loop, i.e. one of
    them (transitively, through blocked_by, deleted todos included) is blocked by todo_id."""
    seen: set[str] = set()
    stack = list(new_blockers)
    while stack:
        cur = stack.pop()
        if cur == todo_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        doc = get_links_graph_docs([cur])[cur]
        if doc:
            stack.extend(doc.get("blocked_by") or [])
    return False


def _aware(dt: datetime.datetime) -> datetime.datetime:
    """Stored timestamps should carry an offset; a naive one is taken as UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=datetime.UTC)


def _parse_aware(stamp: str) -> datetime.datetime:
    return _aware(datetime.datetime.fromisoformat(stamp))


def archive_expired(now: datetime.datetime | None = None, days: int = ARCHIVE_AFTER_DAYS) -> int:
    """Move todos deleted at least `days` ago, with everything beneath them, from
    "todos" to the archive collection. Returns how many documents moved.

    Deleting only flags the top of a subtree, so the descendants go with it or
    they would sit in "todos" unreachable and still be read on every tree load.
    Todos deleted before deleted_at existed have no date: they get one now, so
    their 30 days start today. The candidates are found with plain reads, then
    each chunk moves in a transaction that re-reads its documents: one changed
    since (undeleted, edited, reparented) stays put, and so does everything
    beneath it, until the next run. The archive copy and the delete commit
    together with the revision bump.
    """
    now = now or _now_utc()
    cutoff = now - datetime.timedelta(days=days)
    moving: dict[str, dict] = {}
    for doc in _state.todos.where("deleted", "==", True).stream():
        data = doc.to_dict()
        stamp = data.get("deleted_at")
        if stamp is None:
            doc.reference.update({"deleted_at": now.isoformat()})
        elif _parse_aware(stamp) <= cutoff and data["todo_id"] not in moving:
            moving[data["todo_id"]] = data
            for below in db_firestore_helpers.get_subtree_docs(_state.todos, data["todo_id"]):
                moving.setdefault(below["todo_id"], below)

    docs = list(moving.values())  # parents come before their children
    client = get_conn()
    archive = client.collection(ARCHIVE_COLLECTION)
    rev_ref = client.collection(REV_COLLECTION).document(REV_DOC)
    skipped: set[str] = set()
    moved: list[dict] = []

    @firestore.transactional
    def move_chunk(tx, chunk: list[dict]) -> list[dict]:
        # All reads first: Firestore rejects a read after a write.
        fresh = {d["todo_id"]: _state.todos.document(d["todo_id"]).get(transaction=tx).to_dict()
                 for d in chunk}
        rev_snap = rev_ref.get(transaction=tx)
        going = []
        for data in chunk:
            unchanged = fresh[data["todo_id"]] == data
            if unchanged and data.get("parent_id") not in skipped:
                going.append(data)
            else:
                skipped.add(data["todo_id"])
        for data in going:
            tx.set(archive.document(data["todo_id"]), {**data, "archived_at": now.isoformat()})
            tx.delete(_state.todos.document(data["todo_id"]))
        if going:
            prev = rev_snap.to_dict().get("value", 0) if rev_snap.exists else 0
            tx.set(rev_ref, {"value": prev + 1})
        return going

    for start in range(0, len(docs), 200):
        moved.extend(move_chunk(client.transaction(), docs[start:start + 200]))
    # Images go last: a crash before this leaves orphan blobs (the orphan sweep
    # collects them), never a todo pointing at a missing image.
    for data in moved:
        if data.get("attachments"):
            blobstore.get_store().delete_prefix(blobstore.todo_prefix(data["todo_id"]))
    return len(moved)

def sweep_orphan_blobs(min_age: datetime.timedelta = datetime.timedelta(hours=1)) -> int:
    """Delete attachment blobs no todo references (a crash between a todo write
    and its blob delete, or an upload whose commit never happened). Blobs younger
    than min_age are left alone: an upload puts its blob before the todo commit.
    Returns how many were deleted. Safe to repeat."""
    store = blobstore.get_store()
    cutoff = _now_utc() - min_age
    known: dict[str, set[str]] = {}
    removed = 0
    for key, created in store.list_blobs("todos/"):
        parts = key.split("/")
        if len(parts) != 3 or _aware(created) > cutoff:
            continue
        todo_id, attachment_id = parts[1], parts[2]
        if todo_id not in known:
            snap = _state.todos.document(todo_id).get()
            known[todo_id] = {a["id"] for a in (snap.to_dict() or {}).get("attachments") or []}
        if attachment_id not in known[todo_id]:
            store.delete(key)
            removed += 1
    return removed

def _claim_archive_run(now: datetime.datetime) -> bool:
    """Take the archive run: True for exactly one instance at a time. It fails
    while a successful run is under a day old (last_success) or another
    instance holds a live lease (lease_until). The lease is short so a crashed
    or CPU-starved run is retried soon; only _finish_archive_run(ok=True) burns
    the daily claim."""
    ref = get_conn().collection(REV_COLLECTION).document(ARCHIVE_DOC)

    @firestore.transactional
    def claim(tx) -> bool:
        snap = ref.get(transaction=tx)
        doc = snap.to_dict() if snap.exists else {}
        last = doc.get("last_success") or doc.get("last_run")
        if last and now - _parse_aware(last) < datetime.timedelta(seconds=_ARCHIVE_CHECK_SECONDS):
            return False
        lease = doc.get("lease_until")
        if lease and _parse_aware(lease) > now:
            return False
        tx.set(ref, {"last_success": last, "lease_until": (now + _ARCHIVE_LEASE).isoformat()})
        return True

    return claim(get_conn().transaction())

def _finish_archive_run(now: datetime.datetime, ok: bool) -> None:
    """Release the lease; on success also record the daily last_success."""
    ref = get_conn().collection(REV_COLLECTION).document(ARCHIVE_DOC)
    if ok:
        ref.set({"last_success": now.isoformat(), "lease_until": None})
    else:
        ref.update({"lease_until": None})

def maybe_archive_expired() -> int:
    """archive_expired plus the orphan-blob sweep, at most once a day across all
    instances and one at a time per process. Meant to run off the request path
    (see _load_tree). A failure releases the claim so a later read retries; this
    process backs off for _ARCHIVE_RETRY_SECONDS first."""
    now_m = time.monotonic()
    if _state.archive_checked is not None and now_m - _state.archive_checked < _ARCHIVE_CHECK_SECONDS:
        return 0
    if not _archive_lock.acquire(blocking=False):
        return 0
    try:
        _state.archive_checked = time.monotonic()
        started = _now_utc()
        if not _claim_archive_run(started):
            return 0
        try:
            moved = archive_expired(_now_utc())
            sweep_orphan_blobs()
        except Exception:
            _state.archive_checked = time.monotonic() - _ARCHIVE_CHECK_SECONDS + _ARCHIVE_RETRY_SECONDS
            with contextlib.suppress(Exception):  # the lease expires by itself
                _finish_archive_run(started, ok=False)
            raise
        _finish_archive_run(_now_utc(), ok=True)
        return moved
    finally:
        _archive_lock.release()


# ---- push reminders (see app/push.py) ----
PUSH_DEVICES = "push_devices"
PUSH_SENT = "push_sent"


def upsert_push_device(dev_id: str, token: str, tz: str, platform: str) -> None:
    get_conn().collection(PUSH_DEVICES).document(dev_id).set(
        {"token": token, "tz": tz, "platform": platform, "updated_at": _now_utc()})


def delete_push_device(dev_id: str) -> None:
    get_conn().collection(PUSH_DEVICES).document(dev_id).delete()


def list_push_devices() -> list[dict]:
    return [{"id": d.id, **d.to_dict()} for d in get_conn().collection(PUSH_DEVICES).stream()]


def get_push_marker(key: str) -> list[str] | None:
    """The todo ids stored with a sent-marker, or None when nothing was sent."""
    snap = get_conn().collection(PUSH_SENT).document(key).get()
    return list(snap.to_dict().get("todo_ids") or []) if snap.exists else None


def put_push_marker(key: str, todo_ids: list[str], expires_at: datetime.datetime) -> None:
    # expires_at feeds a Firestore TTL policy on this collection.
    get_conn().collection(PUSH_SENT).document(key).set({"todo_ids": todo_ids, "expires_at": expires_at})


def get_due_todos(before: datetime.datetime) -> list[models.Todo]:
    """Open, live todos whose due date sorts before `before` (naive ISO strings, so
    a string range query). Only these documents are read, never the whole collection."""
    query = (get_conn().collection("todos")
             .where("done", "==", False).where("deleted", "==", False)
             .where("due_date", "<", before.isoformat()))
    return [db_firestore_helpers.doc_to_todo(d.to_dict()) for d in query.stream()]
