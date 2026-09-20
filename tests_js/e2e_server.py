"""The app with the sign-in gate switched off, for scripts/e2e.sh only.

The gate needs a Firebase ID token, which a script cannot mint. The override lives
here, outside app/, so it can never ship in the image (.dockerignore allows only
app/ and web/) and production code has no test backdoor. Emulator only:
FIRESTORE_EMULATOR_HOST must be set, or this refuses to start."""
import os
import sys

if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
    sys.exit("refusing to run without FIRESTORE_EMULATOR_HOST (use scripts/e2e.sh)")
os.environ.setdefault("ALLOWED_EMAIL", "e2e@example.com")

from app.auth import require_user  # noqa: E402
from app.main import app  # noqa: E402

app.dependency_overrides[require_user] = lambda: None
