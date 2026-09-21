from __future__ import annotations
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Header, Query, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import contextlib
import datetime
import logging
import re
from pathlib import Path
from typing import Callable
import uuid
from app import attachments
from app import blobstore
from app import db
from app import ics
from app import models
from app import next_up
from app import push
from app import tasks
from app import auth
from app.auth import require_user

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# The txn id becomes a Firestore document id, so only accept a plain token
# (clients send UUIDs). Firestore also reserves ids of the form __name__.
_TXN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

def check_txn_id(x_txn_id: str | None = Header(None)) -> None:
    if x_txn_id is not None and (
            not _TXN_ID_RE.match(x_txn_id) or (x_txn_id.startswith("__") and x_txn_id.endswith("__"))):
        raise HTTPException(400, "invalid X-Txn-Id")

log = logging.getLogger(__name__)

@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    # Connect at startup, not import, so importing app.main needs no Firestore
    # (tests drive db.init()/teardown() themselves and never run the lifespan).
    auth.check_config()
    db.init()
    try:
        # Idempotency records only need to outlive a client's retry window.
        db.prune_txn_log()
    except Exception:
        log.exception("txn_log prune skipped")
    yield
    db.teardown()

app = FastAPI(lifespan=lifespan, dependencies=[Depends(require_user), Depends(check_txn_id)])

_UPLOAD_PATH_RE = re.compile(r"^/todos/[^/]+/attachments$")
# Multipart framing adds a little to the file's own size.
_UPLOAD_SLACK_BYTES = 1024 * 1024

@app.middleware("http")
async def _limit_upload_size(request, call_next):
    """Refuse an oversized upload from its Content-Length before the body is read
    (FastAPI parses the multipart form before the route runs). The route still
    checks the real size, for clients that send no length."""
    if request.method == "POST" and _UPLOAD_PATH_RE.match(request.url.path):
        try:
            length = int(request.headers.get("content-length", ""))
        except ValueError:
            length = 0
        if length > models.MAX_ATTACHMENT_BYTES + _UPLOAD_SLACK_BYTES:
            return JSONResponse({"detail": "image too large (10 MB max)"}, status_code=413)
    return await call_next(request)


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
        raise HTTPException(404, "todo not found")
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

@app.post("/push/devices")
def register_push_device(body: push.DeviceRegistration) -> dict:
    """The installed app reports its FCM token and timezone at every launch."""
    if not push.valid_tz(body.tz):
        raise HTTPException(400, "unknown timezone")
    db.upsert_push_device(push.device_id(body.token), body.token, body.tz, body.platform)
    return {"ok": True}

@app.post("/push/devices/unregister")
def unregister_push_device(body: push.TokenOnly) -> dict:
    db.delete_push_device(push.device_id(body.token))
    return {"ok": True}

@app.post("/internal/notify")
def notify() -> dict:
    """Cloud Scheduler tick (OIDC-verified in require_user): send due reminders."""
    return push.run_notify(datetime.datetime.now(datetime.timezone.utc), send=push.send_fcm)

@app.post("/internal/budget-alert")
def budget_alert(body: push.PubSubEnvelope) -> dict:
    """Pub/Sub push of a Cloud Billing budget notification (OIDC-verified in require_user):
    tell the owner's devices immediately (rule #1: zero GCP cost)."""
    return push.run_budget_alert(body.message.data, datetime.datetime.now(datetime.timezone.utc), send=push.send_fcm)

@app.post("/internal/notify-todo")
def notify_todo(body: push.HeadsUp) -> dict:
    """Cloud Tasks delivery for one heads-up (OIDC-verified in require_user)."""
    return push.run_heads_up(body.todo_id, body.due, datetime.datetime.now(datetime.timezone.utc), send=push.send_fcm)

def _saved(result: tuple, background: BackgroundTasks, todo_of: Callable[[dict], dict | None] = lambda body: body,
           schedule: bool = True) -> Response:
    """Reply for a finished write, then make the heads-up task for a todo it saved
    (best-effort, after the response, outside the transaction; a replayed retry just finds the
    task already there). schedule=False for writes that can't change a reminder."""
    status, body = result[0], result[1]
    if status == 200 and schedule:
        background.add_task(tasks.schedule_from_body, todo_of(body))
    return _reply(*result)

@app.post("/todos", response_model=None)
def create_todo(body: models.TodoCreate, background: BackgroundTasks,
                x_txn_id: str | None = Header(None)) -> Response:
    def create() -> tuple[int, dict | None]:
        todo = models.Todo(title = body.title)
        if body.due_date:
            todo.due_date = body.due_date
        db.create_todo(todo)
        return 200, jsonable_encoder(todo)

    return _saved(db.run_atomic(x_txn_id, create), background)

@app.get("/calendar/link")
def calendar_link() -> dict:
    """For the More panel (signed in): where the calendar feed lives, or enabled=false."""
    path = auth.calendar_feed_path()
    return {"enabled": path is not None, "path": path}

@app.get("/calendar/{token}.ics", response_model=None)
def calendar_feed(token: str) -> Response:
    """Read-only iCalendar feed of open dated todos. The token in the path is checked
    by require_user (app/auth.py); the parameter is only there to shape the route."""
    _, todos_by_id = db.get_tree(db.get_rev())
    return Response(ics.build_calendar(todos_by_id), media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=300",
                             "Content-Disposition": 'inline; filename="now.ics"'})

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

def _housekeeping() -> None:
    try:
        db.maybe_archive_expired()  # housekeeping must never fail a read
    except Exception:
        log.exception("archiving old deleted todos failed")

def _load_tree(rev: int, background: BackgroundTasks) -> tuple[list[models.Todo], dict[str, models.Todo]]:
    # The sweep runs after the response is sent, so no read pays for it. Tradeoff:
    # on Cloud Run with request-based billing (what we deploy; always-on CPU costs
    # about $30/month) CPU may be throttled once the response is out, so the sweep
    # can crawl until the next request (the daily reminder job, or your next visit); the claim is a 15-minute lease, so a stalled run is simply retaken.
    background.add_task(_housekeeping)
    return db.get_tree(rev)

@app.get("/todos/next", response_model=None)
def get_next_up(background: BackgroundTasks, limit: int = Query(next_up.DEFAULT_LIMIT, ge=1, le=50),
                today: datetime.date | None = None) -> dict:
    """The todos to work on next, best first (see app/next_up.py for the rules).
    With `today` (the client's local date) every todo due then or earlier is included."""
    rev = db.get_rev()
    roots, todosById = _load_tree(rev, background)
    return {"rev": rev, "items": jsonable_encoder(next_up.rank_next_up(roots, todosById, limit, today))}

@app.get("/todos/tree", response_model=dict)
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


@app.get("/todos/trash", response_model=None)
def get_trash() -> dict:
    """Soft-deleted todos, for the Trash view."""
    return {"items": jsonable_encoder(db.get_trash())}

@app.post("/todos/clear-completed", response_model=None)
def clear_completed(x_txn_id: str | None = Header(None)) -> Response:
    """Soft-delete every done todo whose whole subtree is done, in one transaction."""
    def clear() -> tuple[int, dict | None]:
        return 200, {"cleared": _affected(db.clear_completed())}

    return _reply(*db.run_atomic(x_txn_id, clear))

@app.get("/todos/{todo_id}", response_model=models.Todo)
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

@app.patch("/todos/{todo_id}", response_model=None)
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
        if body.links is not None:
            todo.links = body.links
        for name in ("blocked_by", "references"):
            ids = getattr(body, name)
            if ids is not None:
                _check_ids(todo, name, ids)
                setattr(todo, name, ids)
        db.update_todo(todo, bump_version=not view_only)
        return jsonable_encoder(todo)

    return _saved(db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action)), background,
                  schedule=not view_only)

@app.post("/todos/{todo_id}/repeat", response_model=None)
def repeat_todo(todo_id: uuid.UUID, background: BackgroundTasks,
                body: models.TodoRepeatRequest = models.TodoRepeatRequest(),
                x_txn_id: str | None = Header(None)) -> Response:
    """Create the next occurrence of a repeating todo (call it after completing
    the original). A todo spawns at most once: later calls return the same copy."""
    today = body.today or datetime.datetime.now(datetime.timezone.utc).date()

    def action(todo: models.Todo) -> dict:
        if todo.repeat is None:
            raise HTTPException(400, "this todo does not repeat")
        if todo.spawned_id is not None:
            return {"created": False, "spawned_id": str(todo.spawned_id)}
        copy = db.spawn_next_occurrence(todo, today)
        return {"created": True, "spawned_id": str(copy.todo_id), "todo": jsonable_encoder(copy)}

    return _saved(db.run_atomic(x_txn_id, lambda: _apply(todo_id, None, action)),
                  background, lambda body: body.get("todo"))


@app.patch("/todos/{todo_id}/reparent", response_model=None)
def reparent_todo(todo_id: uuid.UUID, body: models.TodoReparent,
                  x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo under another parent (or to the top level) at an index."""
    def action(todo: models.Todo) -> dict:
        try:
            moved = db.reparent_todo(todo, body.parent_id, body.index)
        except db.ReparentError as e:
            if e.kind == "cycle":
                raise HTTPException(400, "cycle")
            raise HTTPException(404, "parent not found")
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

@app.post("/todos/{todo_id}/attachments", response_model=None)
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
        result = db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action))
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
    return _reply(*result)

@app.get("/todos/{todo_id}/attachments/{attachment_id}", response_model=None)
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

@app.delete("/todos/{todo_id}/attachments/{attachment_id}", response_model=None)
def delete_attachment(todo_id: uuid.UUID, attachment_id: str,
                      x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    def action(todo: models.Todo) -> dict:
        if not any(a.id == attachment_id for a in todo.attachments):
            raise HTTPException(404, "attachment not found")
        todo.attachments = [a for a in todo.attachments if a.id != attachment_id]
        db.update_todo(todo)
        return jsonable_encoder(todo)

    result = db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action))
    if result[0] == 200:
        blobstore.get_store().delete(blobstore.key_for(str(todo_id), attachment_id))
    return _reply(*result)

@app.patch("/todos/{todo_id}/undelete", response_model=None)
def undelete_todo_endpoint(todo_id: uuid.UUID, background: BackgroundTasks,
                           x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Restore a soft-deleted todo and its entire subtree (undo)"""
    def action(todo: models.Todo) -> dict:
        restored, affected = db.undelete_todo(models.TodoId(todo_id))
        return {**jsonable_encoder(restored), "affected": _affected(affected)}

    return _saved(db.run_atomic(
        x_txn_id, lambda: _apply(todo_id, if_match, action, include_deleted=True)), background)

@app.post("/todos/{todo_id}/split", response_model=None)
def split_todo(todo_id: uuid.UUID, body: models.TodoSplit, background: BackgroundTasks,
               x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    def action(todo: models.Todo) -> dict:
        # affected is the parent first, then the new children in description
        # order, so the client can map its temporary child ids to real ones by position.
        parent, affected = db.split_into_children(todo, body.descriptions, body.due_date)
        return {**jsonable_encoder(parent), "affected": _affected(affected)}

    result = db.run_atomic(x_txn_id, lambda: _apply(todo_id, if_match, action))
    if result[0] == 200 and body.due_date:
        # The new children (affected[1:]) all carry the split's due date; the parent is unchanged.
        for child in result[1]["affected"][1:]:
            background.add_task(tasks.schedule_from_body,
                                {"todo_id": child["todo_id"], "due_date": jsonable_encoder(body.due_date)})
    return _reply(*result)

@app.patch("/todos/{todo_id}/move/{direction}", response_model=None)
def move_todo(todo_id: uuid.UUID, direction: str,
              x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo up or down within its parent's children (direction: 'up' or 'down')"""
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")

    def action(todo: models.Todo) -> dict:
        try:
            moved = db.reorder_todo(models.TodoId(todo_id), direction)
        except db.MoveError as e:  # only the deliberate refusals; real failures propagate
            raise HTTPException(404 if e.kind == "missing" else 400, f"Cannot move: {e}" if e.kind != "missing" else "todo not found")
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

