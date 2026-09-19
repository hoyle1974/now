#!/bin/bash
# Runs the Python tests against the Firestore emulator (never production).
# The "demo-" project id makes the emulator refuse real GCP credentials.
cd "$(dirname "$0")/.." || exit 1
exec firebase emulators:exec --only firestore --project demo-now-test \
  ".venv/bin/python -m pytest -q ${*:-}"
