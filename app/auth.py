"""Family gate: every API request must carry a Firebase ID token for an email in
ALLOWED_EMAILS (legacy: ALLOWED_EMAIL). The email is the data partition key
(app/tenant.py). Static files stay public (they hold no data)."""
from __future__ import annotations

import hmac
import os
import re

import firebase_admin
from fastapi import HTTPException, Request
from firebase_admin import auth as fb_auth

from app import tenant


def _parse_emails(raw: str) -> tuple[str, ...]:
    """Split on ; , or whitespace ( ';' because gcloud splits env vars on commas), lower-case, de-duplicate."""
    return tuple(dict.fromkeys(e.strip().lower() for e in re.split(r"[;,\s]+", raw) if e.strip()))


def allowed_emails() -> tuple[str, ...]:
    """The allowlist, read from the environment at call time.

    An empty list denies everyone (require_user) and stops the server at
    startup (check_config). Tests change the env, not a module constant."""
    return _parse_emails(os.environ.get("ALLOWED_EMAILS") or os.environ.get("ALLOWED_EMAIL", ""))


def owner() -> str:
    """The first allowed email. The calendar feed and budget alerts are theirs.

    Raises if ALLOWED_EMAILS is empty: check_config() stops the server before this can happen
    in production, so a caller reaching here with nothing configured is a bug, not a user
    input, and should fail loudly rather than bind requests to an empty-string "owner"."""
    emails = allowed_emails()
    if not emails:
        raise RuntimeError("owner() called with no ALLOWED_EMAILS configured")
    return emails[0]


def sharing_enabled() -> bool:
    """SHARING_ENABLED turns sharing between users on (off by default). Off, the share
    routes answer 404, X-Share is refused and no mounts are created; share data stays."""
    return os.environ.get("SHARING_ENABLED", "").strip().lower() in ("1", "true", "yes")


def check_config() -> None:
    if not allowed_emails():
        raise RuntimeError("ALLOWED_EMAILS is not set: export the Google accounts that may sign in, "
                           "first one is the owner (deploy: ALLOWED_EMAILS='you@example.com;kid@example.com' ./deploy.sh)")

_PUBLIC_PATHS = {"/health"}

# Secret-URL calendar feed (GET /calendar/<token>.ics): calendar apps can send no
# headers, so the token is in the path. Unlocks only that route; unset = off.
CALENDAR_TOKEN = os.environ.get("CALENDAR_TOKEN", "")
_CALENDAR_PATH_RE = re.compile(r"^/calendar/([A-Za-z0-9_-]{16,128})\.ics$")

def _calendar_token_ok(request: Request) -> bool:
    m = _CALENDAR_PATH_RE.match(request.url.path)
    return bool(CALENDAR_TOKEN and m and request.method == "GET"
                and hmac.compare_digest(m.group(1).encode(), CALENDAR_TOKEN.encode()))

def calendar_feed_path(user: str) -> str | None:
    """The secret feed path for that signed-in user to show, or None when the feed is off
    or the user is not the owner (the token is the owner's)."""
    if user != owner() or not CALENDAR_TOKEN or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", CALENDAR_TOKEN):
        return None
    return f"/calendar/{CALENDAR_TOKEN}.ics"

# Cloud Scheduler calls these with a Google-signed OIDC token. Read at call time
# so the deployed env vars (and tests) decide; either unset turns the route off.
# Callers: Scheduler (daily digest), Cloud Tasks (heads-ups), Pub/Sub (budget alerts).
_SCHEDULER_PATHS = {"/internal/notify", "/internal/notify-todo", "/internal/budget-alert"}
_SCHEDULER_PATH_PREFIXES = ("/internal/sync-calendar/",)


def _verify_oidc(token: str, audience: str) -> dict:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(token, google_requests.Request(), audience)

def verify_scheduler(request: Request) -> None:
    audience = os.environ.get("NOTIFY_AUDIENCE", "")
    caller = os.environ.get("NOTIFY_CALLER", "").lower()
    if not audience or not caller:
        raise HTTPException(403, "Notifications are not enabled")
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Scheduler token required")
    try:
        claims = _verify_oidc(header[7:].strip(), audience)
    except Exception:
        raise HTTPException(401, "Invalid scheduler token") from None
    if not claims.get("email_verified") or (claims.get("email") or "").lower() != caller:
        raise HTTPException(403, "Not the scheduler")

def require_user(request: Request) -> None:
    if request.url.path in _PUBLIC_PATHS:
        return
    if request.url.path in _SCHEDULER_PATHS or request.url.path.startswith(_SCHEDULER_PATH_PREFIXES):
        verify_scheduler(request)  # no user: the handlers bind one with tenant.as_user
        return
    if _calendar_token_ok(request):
        request.state.user = owner()
        return
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    try:
        claims = fb_auth.verify_id_token(header[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid or expired token") from None
    email = (claims.get("email") or "").lower()
    if not claims.get("email_verified") or email not in allowed_emails():
        raise HTTPException(403, "Not allowed")
    request.state.user = email


async def bind_user(request: Request) -> None:
    """Runs after require_user. Async on purpose: it executes in the request's own task,
    so the ContextVar it sets is copied into the worker thread that runs a sync route."""
    email = getattr(request.state, "user", None)
    if email:
        # No paired tenant.reset(): each request runs in its own asyncio Task with a
        # copied context (and run_in_threadpool copies that context into worker threads
        # too), so this binding never leaks into another request.
        tenant.set_user(email)
