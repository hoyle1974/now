from __future__ import annotations
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, HTTPException, Header, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Callable
import uuid
from app import db
from app import models

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Routes go here.

db.init()

try:
    # Idempotency records only need to outlive a client's retry window.
    db.prune_txn_log()
except Exception as e:
    print(f"txn_log prune skipped: {e}")

def _parse_if_match(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip().strip('"'))
    except ValueError:
        raise HTTPException(400, "If-Match must be an integer version")

def _reply(status: int, body: dict | None) -> Response:
    if body is None:
        return Response(status_code=status)
    return JSONResponse(body, status_code=status)

def _apply(todo_id: uuid.UUID, if_match: str | None, action: Callable[[models.Todo], dict | None],
           include_deleted: bool = False, missing_ok: bool = False) -> tuple[int, dict | None]:
    """Load the todo, enforce If-Match, run the write. A stale version returns
    (409, current todo) so the client can rebase without an extra read.

    Runs inside db.run_atomic, i.e. one transaction: the action must read
    before it writes and return the updated todo rather than re-reading it.
    """
    tid = models.TodoId(todo_id)
    todo = db.get_deleted_todo(tid) if include_deleted else db.get_todo(tid)
    if todo is None:
        if missing_ok:
            return 204, None
        raise HTTPException(404)
    expected = _parse_if_match(if_match)
    if expected is not None and todo.version != expected:
        return 409, jsonable_encoder(todo)
    result = action(todo)
    return (200 if result is not None else 204), result

def _affected(pairs: list[tuple[str, int]]) -> list[dict]:
    return [{"todo_id": tid, "version": version} for tid, version in pairs]

@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run"""
    return {"status": "ok"}

@app.post("/todos", response_model=None)
def create_todo(body: models.TodoCreate, x_txn_id: str | None = Header(None)) -> Response:
    def create() -> tuple[int, dict | None]:
        todo = models.Todo(title = body.title)
        if body.due_date:
            todo.due_date = body.due_date
        db.create_todo(todo)
        return 200, jsonable_encoder(todo)

    return _reply(*db.run_atomic(x_txn_id, create))

def _print_todo(indent:int, todo: models.Todo) -> None:
    print(f"{'':>{indent * 2}}{todo.title} Create:{todo.create_date} Due:{todo.due_date} [{'done' if todo.done else 'not done'}]")
    for child_id in todo.child_ids:
        _print_todo(indent+1, db.get_todo(child_id))

@app.get("/todos/print", response_model=None)
def print_all_todos() -> None:
    for todo in db.get_root_todos():
        _print_todo(0,todo)


@app.get("/todos/root", response_model=list[models.Todo])
def list_todos() -> list[models.Todo]:
    return db.get_root_todos()

@app.get("/todos/tree", response_model=dict)
def get_tree() -> dict:
    """Get the full todo tree in one request: { roots: [...], todosById: {...} }"""
    roots = db.get_root_todos()
    todosById = {}

    def collect_tree(todo):
        todosById[str(todo.todo_id)] = todo
        for child_id in todo.child_ids:
            child = db.get_todo(child_id)
            if child:
                collect_tree(child)

    for root in roots:
        collect_tree(root)

    return {
        "roots": roots,
        "todosById": todosById
    }


@app.get("/todos/{todo_id}", response_model=models.Todo)
def get_todo(todo_id: uuid.UUID) -> models.Todo:
    todo =  db.get_todo(models.TodoId(todo_id))

    if todo is None:
        raise HTTPException(404)

    return todo

@app.patch("/todos/{todo_id}", response_model=None)
def update_todo(todo_id: uuid.UUID, body: models.TodoUpdate,
                x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
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
        db.update_todo(todo)
        return jsonable_encoder(todo)

    return _reply(*db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action)))

@app.patch("/todos/{todo_id}/parent/{parent_id}", response_model=None)
def update_todo_parent(todo_id: uuid.UUID, body: models.TodoUpdateParent,
                       x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    def action(todo: models.Todo) -> dict:
        result = db.update_parent_id(todo, body.parent_id)
        if result is None:
            raise HTTPException(404)
        return jsonable_encoder(result)

    return _reply(*db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action)))


@app.delete("/todos/{todo_id}", status_code=204, response_model=None)
def delete_todo(todo_id: uuid.UUID,
                x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    # Soft delete - mark as deleted instead of removing
    def action(todo: models.Todo) -> None:
        todo.deleted = True
        db.update_todo(todo)
        return None

    return _reply(*db.run_atomic(
        x_txn_id, lambda: _apply(todo_id, if_match, action, missing_ok=True)))

@app.patch("/todos/{todo_id}/undelete", response_model=None)
def undelete_todo_endpoint(todo_id: uuid.UUID,
                           x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Restore a soft-deleted todo and its entire subtree (undo)"""
    def action(todo: models.Todo) -> dict:
        restored, affected = db.undelete_todo(models.TodoId(todo_id))
        return {**jsonable_encoder(restored), "affected": _affected(affected)}

    return _reply(*db.run_atomic(
        x_txn_id, lambda: _apply(todo_id, if_match, action, include_deleted=True)))

@app.post("/todos/{todo_id}/split", response_model=None)
def split_todo(todo_id: uuid.UUID, body: models.TodoSplit,
               x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    def action(todo: models.Todo) -> dict:
        # affected is the parent first, then the new children in description
        # order, so the client can map its temporary child ids to real ones by position.
        parent, affected = db.split_into_children(todo, body.descriptions, body.due_date)
        return {**jsonable_encoder(parent), "affected": _affected(affected)}

    return _reply(*db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action)))

@app.patch("/todos/{todo_id}/move/{direction}", response_model=None)
def move_todo(todo_id: uuid.UUID, direction: str,
              x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo up or down within its parent's children (direction: 'up' or 'down')"""
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")

    def action(todo: models.Todo) -> dict:
        if todo.parent_id is None:
            raise HTTPException(404, "todo not found or has no parent")
        try:
            moved = db.reorder_todo(models.TodoId(todo_id), direction)
        except Exception as e:
            raise HTTPException(400, f"Cannot move: {str(e)}")
        return jsonable_encoder(moved)

    return _reply(*db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action)))


app.mount("/", StaticFiles(directory="web", html=True), name="web")

