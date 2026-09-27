"""Todo CRUD, tree reads, moves and splits."""
from __future__ import annotations

import datetime
import logging
import random
import uuid

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder

from app import auth, db, models, next_up, shares, tasks, tenant, types
from app import migrate
from app.routes.common import affected_refs, apply, atomic, check_share_root, reply, revs, saved

log = logging.getLogger(__name__)
router = APIRouter()

def _check_accepts_children(parent_id) -> None:
    if parent_id is None:
        return
    parent = db.get_todo(models.TodoId(parent_id) if not isinstance(parent_id, models.TodoId) else parent_id)
    if parent is not None and not types.can(parent, "allowsUserChildren"):
        raise HTTPException(400, f"{types.caps(parent.type)['label']} does not accept added items")

def _check_mount(todo: models.Todo) -> None:
    """A mount moves, is removed and restored by its owner-person alone, and only while
    its share is live for them."""
    share = shares.get(str(todo.todo_id))
    if share is None or share.state != "active" or not shares.is_member(share, tenant.current()):
        raise HTTPException(403, "share revoked")

def _check_editable(todo: models.Todo, allowed: bool) -> None:
    """Content edits and deletes are blocked for a type marked read-only in the
    registry (editable: false — e.g. calendar_event, server-managed by sync).
    Collapse is exempt (UI state). A priority-only change is exempt too: the
    user owns that field and the feed never copies it. `allowed` is true for
    those patches."""
    if allowed:
        return
    if not types.can(todo, "editable"):
        raise HTTPException(400, f"{types.caps(todo.type)['label']} is not editable")

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

    return saved(atomic(x_txn_id, create), background)

@router.get("/todos/root", response_model=list[models.Todo])
def list_todos(background: BackgroundTasks) -> list[models.Todo]:
    todos = db.get_root_todos()
    _nudge_stale_calendars(todos, background)
    return todos

def _housekeeping() -> None:
    try:
        db.maybe_archive_expired()  # housekeeping must never fail a read
    except Exception:
        log.exception("archiving old deleted todos failed")

def _nudge_stale_calendars(todos: list[models.Todo] | dict, background: BackgroundTasks) -> None:
    """For each live `calendar` in a just-loaded tree/root list, enqueue a sync if stale.
    Runs as a background task (after the response is sent) so a slow/dead feed URL
    never adds latency to the read; the Cloud Task enqueue call itself is a fast
    Cloud Tasks API call, not the ICS fetch."""
    values = todos.values() if isinstance(todos, dict) else todos
    now = datetime.datetime.now(datetime.UTC)
    for t in values:
        if t.type == "calendar":
            background.add_task(tasks.enqueue_calendar_sync, str(t.todo_id), t.last_synced_at, now)

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
    With `today` (the client's local date) every todo due then or earlier is included.
    Calendar events do not consume `limit`; events due then or earlier are added on top.
    High-priority items are included ahead of that list; low-priority items only fill
    slots still short of `limit`."""
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
    _nudge_stale_calendars(todosById, background)

    return {
        "rev": rev,
        "revs": revs(rev),
        "roots": roots,
        "todosById": todosById
    }

TRASH_PAGE_MAX = 100  # a hard cap on one page, whatever the client asks for

@router.get("/todos/trash", response_model=None)
def get_trash(limit: int = Query(50, ge=1, le=TRASH_PAGE_MAX), offset: int = Query(0, ge=0),
              q: str = Query("", max_length=200)) -> dict:
    """One page of the trash, one entry per trashed item (see db.get_trash), most recently
    deleted first. `deleted_with` is the title of the deleted parent an item went with, else
    null; `trashed_at` is when it went to the trash (an item inside a parent has no delete date
    of its own). `q` filters by title, colour and links. `has_more` says whether a next page
    (offset + len(items)) exists."""
    entries, has_more = db.get_trash(limit, offset, q)
    return {"items": [{**jsonable_encoder(todo), "deleted_with": deleted_with,
                       "trashed_at": models.as_utc_instant(trashed_at)}
                      for todo, deleted_with, trashed_at in entries],
            "has_more": has_more, "next_offset": offset + len(entries)}

@router.post("/todos/clear-completed", response_model=None)
def clear_completed(x_txn_id: str | None = Header(None)) -> Response:
    """Soft-delete every done todo whose whole subtree is done.

    One transaction when the plan fits in CLEAR_COMPLETED_BATCH writes; several
    batches above that, so Firestore's 500-write cap is not hit.
    """
    return reply(*db.run_clear_completed(x_txn_id))

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
    # Priority is content the user owns even on a read-only event, so it is
    # allowed there but still takes If-Match and bumps the version.
    view_only = body.model_fields_set == {"collapsed"}
    readonly_ok = bool(body.model_fields_set) and body.model_fields_set <= {"collapsed", "priority"}
    if view_only:
        if_match = None
    share = shares.bound()
    if share is not None:
        if view_only:
            return _collapse_shared(share, todo_id, bool(body.collapsed))
        if not shares.can_write(share, tenant.current()):
            raise HTTPException(403, "read only")

    def action(todo: models.Todo) -> dict:
        _check_editable(todo, readonly_ok)
        # Reads before any write (Firestore transactions), like _check_ids below.
        purge = db.calendar_purge_plan(todo) if body.deleted and not todo.deleted else None
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
        if body.priority is not None:
            todo.priority = body.priority
        if "repeat" in body.model_fields_set:
            # An explicit null clears the rule; omitting the field leaves it alone.
            todo.repeat = body.repeat
        if "color" in body.model_fields_set:
            todo.color = body.color
        if body.type is not None:
            todo.type = body.type  # only the label changes; due_date, repeat and done stay as they are
        if "calendar_url" in body.model_fields_set:
            todo.calendar_url = body.calendar_url
        if body.links is not None:
            todo.links = body.links
        if "content" in body.model_fields_set:
            todo.content = (body.content or "").strip() or None
        for name in ("blocked_by", "references"):
            ids = getattr(body, name)
            if ids is not None:
                _check_ids(todo, name, ids)
                setattr(todo, name, ids)
        if purge:
            db.apply_calendar_purge(purge, todo)
        db.update_todo(todo, bump_version=not view_only)
        return jsonable_encoder(todo)

    return saved(atomic(x_txn_id, lambda: apply(todo_id, if_match, action, mount_ok=view_only)), background,
                  schedule=not view_only)

def _collapse_shared(share: shares.Share, todo_id: uuid.UUID, collapsed: bool) -> Response:
    """Collapsing a shared node is the member's own view state, never a write to the share
    (so a read-only member may do it, and one member's collapse is not everyone's)."""
    todo = db.get_todo(models.TodoId(todo_id))
    if todo is None:
        raise HTTPException(404, "todo not found")
    shares.set_collapsed(tenant.current(), share.id, str(todo_id), collapsed)
    todo.collapsed = collapsed
    return reply(200, jsonable_encoder(todo))

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

    return saved(atomic(x_txn_id, lambda: apply(todo_id, None, action)),
                  background, lambda body: body.get("todo"))

@router.patch("/todos/{todo_id}/reparent", response_model=None)
def reparent_todo(todo_id: uuid.UUID, body: models.TodoReparent,
                  x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo under another parent (or to the top level) at an index.

    `parent_share` names the partition the new parent is in (a share id, or null for the
    caller's own list); omitted means "same partition as the todo". When it differs from
    where the todo is, the todo and its subtree migrate there (app/migrate.py)."""
    here = tenant.partition()
    target = here
    if "parent_share" in body.model_fields_set and auth.sharing_enabled():
        target = f"users/{tenant.current()}" if body.parent_share is None else f"shares/{body.parent_share}"
    if target != here:
        return _reparent_across(todo_id, body, here, target)

    def action(todo: models.Todo) -> dict:
        if todo.type == "mount":
            _check_mount(todo)
        else:
            _check_editable(todo, False)
        check_share_root(todo, "move")
        _check_accepts_children(body.parent_id)
        try:
            moved = db.reparent_todo(todo, body.parent_id, body.index)
        except db.ReparentError as e:
            if e.kind == "cycle":
                raise HTTPException(400, "cycle") from e
            raise HTTPException(404, "parent not found") from e
        return jsonable_encoder(moved)

    return reply(*atomic(x_txn_id, lambda: apply(todo_id, if_match, action, mount_ok=True)))

_MIGRATION_STATUS = {"crosses share boundary": 409, "not eligible": 400, "too large": 413,
                     "parent not found": 404}

def _reparent_across(todo_id: uuid.UUID, body: models.TodoReparent, here: str, target: str) -> Response:
    """Drag an item into or out of a share: its whole subtree changes partition. Needs edit
    rights on both sides (bind_partition already checked the source's)."""
    todo = db.get_todo(models.TodoId(todo_id))
    if todo is None:
        raise HTTPException(404, "todo not found")
    if todo.type == "mount" or (shares.bound() is not None and str(todo_id) == shares.bound().id):
        raise HTTPException(409, "crosses share boundary")
    target_share = shares.check_partition_write(target)
    parent = None if body.parent_id is None else str(body.parent_id)
    if parent is not None:
        with tenant.as_partition(target):
            parent_todo = db.get_todo(body.parent_id)
        if parent_todo is None:
            raise HTTPException(404, "parent not found")
        if not types.can(parent_todo, "allowsUserChildren"):
            raise HTTPException(400, f"{types.caps(parent_todo.type)['label']} does not accept added items")
    try:
        migrate.migrate_subtree(here, str(todo_id), target, kind="move", dst_parent=parent, index=body.index)
    except migrate.MigrationError as e:
        raise HTTPException(_MIGRATION_STATUS.get(e.detail, 400), e.detail) from e
    shares.bind_partition(target, target_share)
    moved = db.get_todo(models.TodoId(todo_id))
    return reply(200, jsonable_encoder(moved))

@router.delete("/todos/{todo_id}", status_code=204, response_model=None)
def delete_todo(todo_id: uuid.UUID,
                x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    # Soft delete - mark as deleted instead of removing. A calendar's synced events
    # (also those of a calendar inside the deleted item) are hard-deleted instead:
    # the feed brings them back if the calendar is restored.
    def action(todo: models.Todo) -> None:
        if todo.type == "mount":  # "Remove from my list": only this person's mount goes
            todo.deleted = True
            db.update_todo(todo)
            return None
        _check_editable(todo, False)
        check_share_root(todo, "delete")
        purge = db.calendar_purge_plan(todo)
        todo.deleted = True
        db.apply_calendar_purge(purge, todo)
        db.update_todo(todo)
        return None

    return reply(*atomic(
        x_txn_id, lambda: apply(todo_id, if_match, action, missing_ok=True, mount_ok=True)))

@router.patch("/todos/{todo_id}/undelete", response_model=None)
def undelete_todo_endpoint(todo_id: uuid.UUID, background: BackgroundTasks,
                           x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Restore a soft-deleted todo and its entire subtree (undo)"""
    def action(todo: models.Todo) -> dict:
        if todo.type == "mount":
            _check_mount(todo)
        check_share_root(todo, "undelete")
        restored, affected = db.undelete_todo(models.TodoId(todo_id))
        return {**jsonable_encoder(restored), "affected": affected_refs(affected)}

    return saved(atomic(
        x_txn_id, lambda: apply(todo_id, if_match, action, include_deleted=True, mount_ok=True)), background)

@router.post("/todos/{todo_id}/split", response_model=None)
def split_todo(todo_id: uuid.UUID, body: models.TodoSplit, background: BackgroundTasks,
               x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    # A type without a due date never gets one, so nothing is scheduled for it either.
    due_date = body.due_date if types.has_field_type(body.type, "due_date") else None
    # One note can be born with its body. Add several stays titles only.
    text = (body.content or "").strip()
    content = text if (
        text and len(body.descriptions) == 1 and types.has_field_type(body.type, "content")
    ) else None

    def action(todo: models.Todo) -> dict:
        _check_accepts_children(todo_id)
        # affected is the parent first, then the new children in description
        # order, so the client can map its temporary child ids to real ones by position.
        parent, affected = db.split_into_children(
            todo, body.descriptions, due_date, body.type or types.DEFAULT, content)
        return {**jsonable_encoder(parent), "affected": affected_refs(affected)}

    result = atomic(x_txn_id, lambda: apply(todo_id, if_match, action))
    if result[0] == 200 and due_date:
        # The new children (affected[1:]) all carry the split's due date; the parent is unchanged.
        for child in result[1]["affected"][1:]:  # type: ignore[index]
            background.add_task(tasks.schedule_from_body,
                                {"todo_id": child["todo_id"], "due_date": jsonable_encoder(due_date)})
    return reply(*result)

@router.post("/todos/{todo_id}/sync", response_model=None)
def sync_now(todo_id: uuid.UUID, background: BackgroundTasks, body: models.SyncNowBody | None = None) -> Response:
    """Manual 'Sync now': enqueues immediately, ignoring staleness."""
    todo = db.get_todo(models.TodoId(todo_id))
    if todo is None:
        raise HTTPException(404, "todo not found")
    if todo.type != "calendar":
        raise HTTPException(400, "only a calendar item can be synced")
    csid = body.client_session_id if body else None
    background.add_task(tasks.enqueue_calendar_sync, str(todo.todo_id), None,
                        datetime.datetime.now(datetime.UTC), client_session_id=csid, manual=True)
    return Response(status_code=202)

@router.patch("/todos/{todo_id}/move/{direction}", response_model=None)
def move_todo(todo_id: uuid.UUID, direction: str,
              x_txn_id: str | None = Header(None), if_match: str | None = Header(None)) -> Response:
    """Move a todo up or down within its parent's children (direction: 'up' or 'down')"""
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")

    def action(todo: models.Todo) -> dict:
        if todo.type == "mount":
            _check_mount(todo)
        else:
            _check_editable(todo, False)
        check_share_root(todo, "move")
        try:
            moved = db.reorder_todo(models.TodoId(todo_id), direction)
        except db.MoveError as e:  # only the deliberate refusals; real failures propagate
            detail = "todo not found" if e.kind == "missing" else f"Cannot move: {e}"
            raise HTTPException(404 if e.kind == "missing" else 400, detail) from e
        return jsonable_encoder(moved)

    return reply(*atomic(x_txn_id, lambda: apply(todo_id, if_match, action, mount_ok=True)))
