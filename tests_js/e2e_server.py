"""The app with the sign-in gate switched off, for scripts/e2e.sh only.

The gate needs a Firebase ID token, which a script cannot mint. The override lives
here, outside app/, so it can never ship in the image (.dockerignore allows only
app/ and web/) and production code has no test backdoor. Emulator only:
FIRESTORE_EMULATOR_HOST must be set, or this refuses to start."""
import os
import sys

if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
    sys.exit("refusing to run without FIRESTORE_EMULATOR_HOST (use scripts/e2e.sh)")
os.environ.setdefault("ALLOWED_EMAILS", "e2e@example.com")

from fastapi import Request

from app.auth import require_user
from app.main import app


def _fake_require_user(request: Request) -> None:
    # Sets request.state.user directly, exactly as the real require_user does,
    # so bind_user still binds a tenant (app/tenant.py) for data access.
    # Normalized the same way (.strip().lower()) so this harness matches production.
    request.state.user = os.environ["ALLOWED_EMAILS"].split(";")[0].strip().lower()


app.dependency_overrides[require_user] = _fake_require_user
