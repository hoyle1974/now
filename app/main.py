from __future__ import annotations
from fastapi.templating import Jinja2Templates
from fastapi import Depends, FastAPI, HTTPException, Header, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import datetime
from pathlib import Path
from typing import Callable
import re
import uuid
from app import db
from app import models
from app import next_up
from app.auth import require_user

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(dependencies=[Depends(require_user)])
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

def _reply(status: int, body: dict | None, prev: int | None = None, rev: int | None = None) -> Response:
    # X-Rev-Prev / X-Rev let the client notice writes made elsewhere: if
    # Prev is ahead of what it last saw, another window wrote in between.
    headers = {} if rev is None else {"X-Rev-Prev": str(prev), "X-Rev": str(rev)}
    if body is None:
        return Response(status_code=status, headers=headers)
    return JSONResponse(body, status_code=status, headers=headers)

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

def _read_app_version() -> str:
    """The version of the web code this container serves: APP_VERSION in
    web/app.js is the single source of truth, so bumping it there is enough."""
    try:
        match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (WEB_DIR / "app.js").read_text())
        return match.group(1) if match else "unknown"
    except OSError:
        return "unknown"

APP_VERSION = _read_app_version()

@app.get("/todos/rev")
def get_rev() -> dict:
    """Cheap change check: one document read. Compare rev with the last seen
    value; a different version means the page is running old code and must reload."""
    return {"rev": db.get_rev(), "version": APP_VERSION}

def _load_tree() -> tuple[list[models.Todo], dict[str, models.Todo]]:
    return db.get_tree()

@app.get("/todos/next", response_model=None)
def get_next_up(limit: int = Query(next_up.DEFAULT_LIMIT, ge=1, le=50)) -> dict:
    """The todos to work on next, best first (see app/next_up.py for the rules)."""
    rev = db.get_rev()
    roots, todosById = _load_tree()
    return {"rev": rev, "items": jsonable_encoder(next_up.rank_next_up(roots, todosById, limit))}

@app.get("/todos/tree", response_model=dict)
def get_tree() -> dict:
    """Get the full todo tree in one request: { roots: [...], todosById: {...} }"""
    # Read the revision first, so it can only be older than the tree we return:
    # the worst case is one redundant refresh, never a missed change.
    rev = db.get_rev()
    roots, todosById = _load_tree()

    return {
        "rev": rev,
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
        db.update_todo(todo, bump_version=not view_only)
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


@app.post("/todos/{todo_id}/repeat", response_model=None)
def repeat_todo(todo_id: uuid.UUID, body: models.TodoRepeatRequest = models.TodoRepeatRequest(),
                x_txn_id: str | None = Header(None)) -> Response:
    """Create the next occurrence of a repeating todo (call it after completing
    the original). A todo spawns at most once: later calls return the same copy."""
    today = body.today or datetime.date.today()

    def action(todo: models.Todo) -> dict:
        if todo.repeat is None:
            raise HTTPException(400, "this todo does not repeat")
        if todo.spawned_id is not None:
            return {"created": False, "spawned_id": str(todo.spawned_id)}
        copy = db.spawn_next_occurrence(todo, today)
        return {"created": True, "spawned_id": str(copy.todo_id), "todo": jsonable_encoder(copy)}

    return _reply(*db.run_atomic(x_txn_id, lambda: _apply(todo_id, None, action)))


@app.patch("/todos/{todo_id}/reparent", response_model=None)
def reparent_todo(todo_id: uuid.UUID, body: models.TodoReparent,
                  x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo under another parent (or to the top level) at an index."""
    def action(todo: models.Todo) -> dict:
        try:
            moved = db.reparent_todo(todo, body.parent_id, body.index)
        except db.ReparentError as e:
            raise HTTPException(400 if e.kind == "cycle" else 404, e.kind)
        return jsonable_encoder(moved)

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
        try:
            moved = db.reorder_todo(models.TodoId(todo_id), direction)
        except Exception as e:
            raise HTTPException(400, f"Cannot move: {str(e)}")
        return jsonable_encoder(moved)

    return _reply(*db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action)))


class RevalidatingStaticFiles(StaticFiles):
    """Static files with ETags but no Cache-Control let iOS home-screen apps
    heuristically reuse a stale page for days; no-cache forces a revalidation."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", RevalidatingStaticFiles(directory=WEB_DIR, html=True), name="web")

