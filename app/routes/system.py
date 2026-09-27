"""Health and version checks."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import db, shares, tenant

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
router = APIRouter()

@router.get("/health")
def health_check(deep: bool = False):
    """Liveness. `?deep=1` also pings Firestore (503 if it cannot)."""
    if not deep:
        return {"status": "ok"}
    try:
        client = db.get_conn()
        if client is None:
            raise RuntimeError("firestore not initialized")
        client.collection("users").document("_").get()
        return {"status": "ok", "firestore": "ok"}
    except Exception:
        raise HTTPException(503, "firestore unavailable") from None

def _read_app_version() -> str:
    """The version of the web code this container serves: APP_VERSION in
    web/app.js is the single source of truth, so bumping it there is enough."""
    try:
        match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (WEB_DIR / "app.js").read_text())
        return match.group(1) if match else "unknown"
    except OSError:
        return "unknown"

APP_VERSION = _read_app_version()

@router.get("/todos/rev")
def get_rev() -> dict:
    """Cheap change check: one document read. Compare rev with the last seen
    value; a different version means the page is running old code and must
    reload. triggered_by is the client_session_id of whoever's write last
    bumped rev, or null — used to suppress the "changes from another device"
    framing for a client's own manually-triggered calendar sync."""
    info = db.get_rev_info()
    return {"rev": info["value"], "revs": shares.revs(tenant.current(), info["value"]), "version": APP_VERSION,
            "triggered_by": info["triggered_by"]}
