"""Single-user gate: every API request must carry a Firebase ID token for
ALLOWED_EMAIL. Static files stay public (they hold no data)."""
from __future__ import annotations
import os
from fastapi import HTTPException, Request
import firebase_admin
from firebase_admin import auth as fb_auth

ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "you@example.com").lower()

_PUBLIC_PATHS = {"/health"}

def require_user(request: Request) -> None:
    if request.url.path in _PUBLIC_PATHS:
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
