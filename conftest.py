"""Safety net: the Firestore backend is the default, and this machine has real
GCP credentials, so refuse to run tests unless they are pointed at the emulator
(use scripts/test.sh)."""
import os

import pytest

if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
    pytest.exit(
        "FIRESTORE_EMULATOR_HOST is not set: refusing to run tests against real "
        "Firestore. Run scripts/test.sh instead.",
        returncode=2,
    )

os.environ["ALLOWED_EMAIL"] = "me@example.com"  # read by app.auth at import

# A demo- project can only ever exist inside the emulator.
os.environ["GOOGLE_CLOUD_PROJECT"] = "demo-now-test"
os.environ["GCLOUD_PROJECT"] = "demo-now-test"
