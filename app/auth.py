"""Single-user gate: every API request must carry a Firebase ID token for
ALLOWED_EMAIL. Static files stay public (they hold no data)."""
from __future__ import annotations
import hmac
import os
from fastapi import HTTPException, Request
import firebase_admin
from firebase_admin import auth as fb_auth

ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "you@example.com").lower()

_PUBLIC_PATHS = {"/health"}

# Long-lived read-only token for the iOS Scriptable lock screen widget, which
# can't refresh Firebase ID tokens. Unlocks only GET /todos/next; unset = off.
WIDGET_TOKEN = os.environ.get("WIDGET_TOKEN", "")
_WIDGET_PATH = "/todos/next"

def _widget_token_ok(request: Request) -> bool:
    supplied = request.headers.get("x-widget-token", "")
    return bool(WIDGET_TOKEN and supplied and request.method == "GET"
                and request.url.path == _WIDGET_PATH
                and hmac.compare_digest(supplied, WIDGET_TOKEN))

def require_user(request: Request) -> None:
    if request.url.path in _PUBLIC_PATHS:
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
    if not claims.get("email_verified") or email != ALLOWED_EMAIL:
        raise HTTPException(403, "Not allowed")
