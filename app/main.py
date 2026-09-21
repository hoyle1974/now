from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth, db, models
from app.auth import require_user
from app.routes import attachments, calendar, notifications, system, todos
from app.routes.common import check_txn_id

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

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

# Order matters: system's /todos/rev must be matched before todos' /todos/{todo_id}.
for _router in (system.router, notifications.router, calendar.router, todos.router, attachments.router):
    app.include_router(_router)

_API_PREFIXES = ("/todos", "/push", "/calendar")


@app.middleware("http")
async def _no_store_api_reads(request, call_next):
    """API JSON has no validators, so a browser (iOS home-screen apps especially) may
    reuse an old answer, e.g. a Next up list without the todo just added. Routes that
    set their own Cache-Control (attachments, the calendar feed) keep it."""
    response = await call_next(request)
    if request.url.path.startswith(_API_PREFIXES) and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


class RevalidatingStaticFiles(StaticFiles):
    """Static files with ETags but no Cache-Control let iOS home-screen apps
    heuristically reuse a stale page for days; no-cache forces a revalidation."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", RevalidatingStaticFiles(directory=WEB_DIR, html=True), name="web")
