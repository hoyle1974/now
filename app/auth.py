"""Single-user gate: every API request must carry a Firebase ID token for
ALLOWED_EMAIL. Static files stay public (they hold no data)."""
from __future__ import annotations
import hmac
import os
from fastapi import HTTPException, Request
import firebase_admin
from firebase_admin import auth as fb_auth

# The one Google account allowed in. No default: an unset value denies everyone
# (require_user) and stops the server at startup (check_config).
ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "").strip().lower()

def check_config() -> None:
    if not ALLOWED_EMAIL:
        raise RuntimeError("ALLOWED_EMAIL is not set: export the Google account that may sign in "
                           "(deploy: ALLOWED_EMAIL=you@example.com ./deploy.sh)")

_PUBLIC_PATHS = {"/health"}

# Long-lived read-only token for the iOS Scriptable lock screen widget, which
# can't refresh Firebase ID tokens. Unlocks only GET /todos/next; unset = off.
WIDGET_TOKEN = os.environ.get("WIDGET_TOKEN", "")
_WIDGET_PATH = "/todos/next"

def _widget_token_ok(request: Request) -> bool:
    supplied = request.headers.get("x-widget-token", "")
    return bool(WIDGET_TOKEN and supplied and request.method == "GET"
                and request.url.path == _WIDGET_PATH
                and hmac.compare_digest(supplied.encode(), WIDGET_TOKEN.encode()))

# Cloud Scheduler calls these with a Google-signed OIDC token. Read at call time
# so the deployed env vars (and tests) decide; either unset turns the route off.
_SCHEDULER_PATHS = {"/internal/notify"}

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
        raise HTTPException(401, "Invalid scheduler token")
    if not claims.get("email_verified") or (claims.get("email") or "").lower() != caller:
        raise HTTPException(403, "Not the scheduler")

def require_user(request: Request) -> None:
    if request.url.path in _PUBLIC_PATHS:
        return
    if request.url.path in _SCHEDULER_PATHS:
        verify_scheduler(request)
        return
    if _widget_token_ok(request):
        return
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    try:
        claims = fb_auth.verify_id_token(header[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    email = (claims.get("email") or "").lower()
    if not ALLOWED_EMAIL or not claims.get("email_verified") or email != ALLOWED_EMAIL:
        raise HTTPException(403, "Not allowed")
