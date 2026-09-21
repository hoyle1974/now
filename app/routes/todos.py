"""Todo CRUD, tree reads, moves and splits."""
from __future__ import annotations

import datetime
import logging
import random
import uuid

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder

from app import db, models, next_up, tasks, types
from app.routes.common import affected_refs, apply, reply, saved

log = logging.getLogger(__name__)
router = APIRouter()

@router.post("/todos", response_model=None)
def create_todo(body: models.TodoCreate, background: BackgroundTasks,
                x_txn_id: str | None = Header(None)) -> Response:
    def create() -> tuple[int, dict | None]:
        # A new top-level project gets a random colour so projects are told apart at a glance.
        todo = models.Todo(title=body.title, color=body.color or random.choice(models.COLORS),
                           type=body.type or types.DEFAULT)
        if body.due_date and types.has_field(todo, "due_date"):
            todo.due_date = body.due_date
        db.create_todo(todo)
        return 200, jsonable_encoder(todo)

    return saved(db.run_atomic(x_txn_id, create), background)

@router.get("/todos/root", response_model=list[models.Todo])
def list_todos() -> list[models.Todo]:
    return db.get_root_todos()

def _housekeeping() -> None:
    try:
        db.maybe_archive_expired()  # housekeeping must never fail a read
    except Exception:
        log.exception("archiving old deleted todos failed")

def _load_tree(rev: int, background: BackgroundTasks) -> tuple[list[models.Todo], dict[str, models.Todo]]:
    # The sweep runs after the response is sent, so no read pays for it. Tradeoff:
    # on Cloud Run with request-based billing (what we deploy; always-on CPU costs
    # about $30/month) CPU may be throttled once the response is out, so the sweep
    # can crawl until the next request (the daily reminder job, or your next visit);
    # the claim is a 15-minute lease, so a stalled run is simply retaken.
    background.add_task(_housekeeping)
    return db.get_tree(rev)

@router.get("/todos/next", response_model=None)
def get_next_up(background: BackgroundTasks, limit: int = Query(next_up.DEFAULT_LIMIT, ge=1, le=50),
                today: datetime.date | None = None) -> dict:
    """The todos to work on next, best first (see app/next_up.py for the rules).
    With `today` (the client's local date) every todo due then or earlier is included."""
    rev = db.get_rev()
    roots, todosById = _load_tree(rev, background)
    return {"rev": rev, "items": jsonable_encoder(next_up.rank_next_up(roots, todosById, limit, today))}

@router.get("/todos/tree", response_model=dict)
def get_tree(background: BackgroundTasks) -> dict:
    """Get the full todo tree in one request: { roots: [...], todosById: {...} }"""
    # Read the revision first, so it can only be older than the tree we return:
    # the worst case is one redundant refresh, never a missed change.
    rev = db.get_rev()
    roots, todosById = _load_tree(rev, background)

    return {
        "rev": rev,
        "roots": roots,
        "todosById": todosById
    }

@router.get("/todos/trash", response_model=None)
def get_trash() -> dict:
    """Everything in the trash, one entry per item (see db.get_trash), for the Trash view.
    `deleted_with` is the title of the deleted parent an item went with, else null;
    `trashed_at` is when it went to the trash (an item inside a parent has no delete date of its own)."""
    return {"items": [{**jsonable_encoder(todo), "deleted_with": deleted_with, "trashed_at": jsonable_encoder(trashed_at)}
                      for todo, deleted_with, trashed_at in db.get_trash()]}

@router.post("/todos/clear-completed", response_model=None)
def clear_completed(x_txn_id: str | None = Header(None)) -> Response:
    """Soft-delete every done todo whose whole subtree is done, in one transaction."""
    def clear() -> tuple[int, dict | None]:
        return 200, {"cleared": affected_refs(db.clear_completed())}

    return reply(*db.run_atomic(x_txn_id, clear))

@router.get("/todos/{todo_id}", response_model=models.Todo)
def get_todo(todo_id: uuid.UUID) -> models.Todo:
    todo =  db.get_todo(models.TodoId(todo_id))

    if todo is None:
        raise HTTPException(404, "todo not found")

    return todo

def _check_ids(todo: models.Todo, name: str, ids: list[models.TodoId]) -> None:
    """Every id must exist (trashed ones count) and not be the todo itself;
    blocked_by must also stay acyclic. Reads only, so safe before the write.
    An id the todo already holds is kept even if its target was archived since
    (it is inert: blocked ignores it), otherwise those lists could never be
    edited again; only newly added ids must exist."""
    strs = [str(i) for i in ids]
    if str(todo.todo_id) in strs:
        raise HTTPException(400, f"{name} cannot contain the todo itself")
    docs = db.get_links_graph_docs(strs)
    held = {str(i) for i in getattr(todo, name)}
    missing = [i for i, d in docs.items() if d is None and i not in held]
    if missing:
        raise HTTPException(400, f"{name}: unknown todo id {missing[0]}")
    if name == "blocked_by" and any(
            db.is_ancestor(str(todo.todo_id), i) or db.is_ancestor(i, str(todo.todo_id)) for i in strs):
        raise HTTPException(400, "blocked_by cannot include a parent or subtask")
    if name == "blocked_by" and db.blocked_by_would_cycle(str(todo.todo_id), strs):
        raise HTTPException(400, "blocked_by would create a cycle")

@router.patch("/todos/{todo_id}", response_model=None)
def update_todo(todo_id: uuid.UUID, body: models.TodoUpdate, background: BackgroundTasks,
                x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    # Collapsing is view state: last write wins, so it skips the If-Match
    # check and doesn't bump the version (no conflicts with content edits).
    view_only = body.model_fields_set == {"collapsed"}
    if view_only:
        if_match = None

    def action(todo: models.Todo) -> dict:
        if body.title is not None:
            todo.title = body.title
        if body.done is not None:
            todo.done = body.done
        if "due_date" in body.model_fields_set:
            # An explicit null clears the due date; omitting the field leaves it alone.
            todo.due_date = body.due_date
        if body.deleted is not None:
            todo.deleted = body.deleted
        if body.collapsed is not None:
            todo.collapsed = body.collapsed
        if "repeat" in body.model_fields_set:
            # An explicit null clears the rule; omitting the field leaves it alone.
            todo.repeat = body.repeat
        if "color" in body.model_fields_set:
            todo.color = body.color
        if body.type is not None:
            todo.type = body.type  # only the label changes; due_date, repeat and done stay as they are
        if body.links is not None:
            todo.links = body.links
        for name in ("blocked_by", "references"):
            ids = getattr(body, name)
            if ids is not None:
                _check_ids(todo, name, ids)
                setattr(todo, name, ids)
        db.update_todo(todo, bump_version=not view_only)
        return jsonable_encoder(todo)

    return saved(db.run_atomic(x_txn_id, lambda: apply(todo_id, if_match, action)), background,
                  schedule=not view_only)

@router.post("/todos/{todo_id}/repeat", response_model=None)
def repeat_todo(todo_id: uuid.UUID, background: BackgroundTasks,
                body: models.TodoRepeatRequest | None = None,
                x_txn_id: str | None = Header(None)) -> Response:
    """Create the next occurrence of a repeating todo (call it after completing
    the original). A todo spawns at most once: later calls return the same copy."""
    today = (body and body.today) or datetime.datetime.now(datetime.UTC).date()

    def action(todo: models.Todo) -> dict:
        if todo.repeat is None:
            raise HTTPException(400, "this todo does not repeat")
        if todo.spawned_id is not None:
            return {"created": False, "spawned_id": str(todo.spawned_id)}
        copy = db.spawn_next_occurrence(todo, today)
        return {"created": True, "spawned_id": str(copy.todo_id), "todo": jsonable_encoder(copy)}

    return saved(db.run_atomic(x_txn_id, lambda: apply(todo_id, None, action)),
                  background, lambda body: body.get("todo"))

@router.patch("/todos/{todo_id}/reparent", response_model=None)
def reparent_todo(todo_id: uuid.UUID, body: models.TodoReparent,
                  x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo under another parent (or to the top level) at an index."""
    def action(todo: models.Todo) -> dict:
        try:
            moved = db.reparent_todo(todo, body.parent_id, body.index)
        except db.ReparentError as e:
            if e.kind == "cycle":
                raise HTTPException(400, "cycle") from e
            raise HTTPException(404, "parent not found") from e
        return jsonable_encoder(moved)

    return reply(*db.run_atomic(x_txn_id, lambda: apply(todo_id, if_match, action)))

@router.delete("/todos/{todo_id}", status_code=204, response_model=None)
def delete_todo(todo_id: uuid.UUID,
                x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    # Soft delete - mark as deleted instead of removing
    def action(todo: models.Todo) -> None:
        todo.deleted = True
        db.update_todo(todo)
        return None

    return reply(*db.run_atomic(
        x_txn_id, lambda: apply(todo_id, if_match, action, missing_ok=True)))

@router.patch("/todos/{todo_id}/undelete", response_model=None)
def undelete_todo_endpoint(todo_id: uuid.UUID, background: BackgroundTasks,
                           x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Restore a soft-deleted todo and its entire subtree (undo)"""
    def action(todo: models.Todo) -> dict:
        restored, affected = db.undelete_todo(models.TodoId(todo_id))
        return {**jsonable_encoder(restored), "affected": affected_refs(affected)}

    return saved(db.run_atomic(
        x_txn_id, lambda: apply(todo_id, if_match, action, include_deleted=True)), background)

@router.post("/todos/{todo_id}/split", response_model=None)
def split_todo(todo_id: uuid.UUID, body: models.TodoSplit, background: BackgroundTasks,
               x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    # A type without a due date never gets one, so nothing is scheduled for it either.
    due_date = body.due_date if types.has_field_type(body.type, "due_date") else None

    def action(todo: models.Todo) -> dict:
        # affected is the parent first, then the new children in description
        # order, so the client can map its temporary child ids to real ones by position.
        parent, affected = db.split_into_children(todo, body.descriptions, due_date, body.type or types.DEFAULT)
        return {**jsonable_encoder(parent), "affected": affected_refs(affected)}

    result = db.run_atomic(x_txn_id, lambda: apply(todo_id, if_match, action))
    if result[0] == 200 and due_date:
        # The new children (affected[1:]) all carry the split's due date; the parent is unchanged.
        for child in result[1]["affected"][1:]:  # type: ignore[index]
            background.add_task(tasks.schedule_from_body,
                                {"todo_id": child["todo_id"], "due_date": jsonable_encoder(due_date)})
    return reply(*result)

@router.patch("/todos/{todo_id}/move/{direction}", response_model=None)
def move_todo(todo_id: uuid.UUID, direction: str,
              x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo up or down within its parent's children (direction: 'up' or 'down')"""
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")

    def action(todo: models.Todo) -> dict:
        try:
            moved = db.reorder_todo(models.TodoId(todo_id), direction)
        except db.MoveError as e:  # only the deliberate refusals; real failures propagate
            detail = "todo not found" if e.kind == "missing" else f"Cannot move: {e}"
            raise HTTPException(404 if e.kind == "missing" else 400, detail) from e
        return jsonable_encoder(moved)

    return reply(*db.run_atomic(x_txn_id, lambda: apply(todo_id, if_match, action)))
