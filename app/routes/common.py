"""Helpers shared by the route modules."""
from __future__ import annotations

import re
import uuid
from collections.abc import Callable

from fastapi import BackgroundTasks, Header, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app import db, models, tasks

# The txn id becomes a Firestore document id, so only accept a plain token
# (clients send UUIDs). Firestore also reserves ids of the form __name__.
_TXN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

def check_txn_id(x_txn_id: str | None = Header(None)) -> None:
    if x_txn_id is not None and (
            not _TXN_ID_RE.match(x_txn_id) or (x_txn_id.startswith("__") and x_txn_id.endswith("__"))):
        raise HTTPException(400, "invalid X-Txn-Id")

def _parse_if_match(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip().strip('"'))
    except ValueError:
        raise HTTPException(400, "If-Match must be an integer version") from None

def reply(status: int, body: dict | None, prev: int | None = None, rev: int | None = None) -> Response:
    # X-Rev-Prev / X-Rev let the client notice writes made elsewhere: if
    # Prev is ahead of what it last saw, another window wrote in between.
    headers = {} if rev is None else {"X-Rev-Prev": str(prev), "X-Rev": str(rev)}
    if body is None:
        return Response(status_code=status, headers=headers)
    return JSONResponse(body, status_code=status, headers=headers)

def apply(todo_id: uuid.UUID, if_match: str | None, action: Callable[[models.Todo], dict | None],
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
        raise HTTPException(404, "todo not found")
    expected = _parse_if_match(if_match)
    if expected is not None and todo.version != expected:
        return 409, jsonable_encoder(todo)
    result = action(todo)
    return (200 if result is not None else 204), result

def affected_refs(pairs: list[tuple[str, int]]) -> list[dict]:
    return [{"todo_id": tid, "version": version} for tid, version in pairs]

def saved(result: tuple, background: BackgroundTasks, todo_of: Callable[[dict], dict | None] = lambda body: body,
           schedule: bool = True) -> Response:
    """Reply for a finished write, then make the heads-up task for a todo it saved
    (best-effort, after the response, outside the transaction; a replayed retry just finds the
    task already there). schedule=False for writes that can't change a reminder."""
    status, body = result[0], result[1]
    if status == 200 and schedule:
        background.add_task(tasks.schedule_from_body, todo_of(body))
    return reply(*result)
