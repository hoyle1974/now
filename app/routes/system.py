"""Health and version checks."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

from app import db

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
router = APIRouter()

@router.get("/health")
def health_check():
    """Health check endpoint for Cloud Run"""
    return {"status": "ok"}

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
    value; a different version means the page is running old code and must reload."""
    return {"rev": db.get_rev(), "version": APP_VERSION}
