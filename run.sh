#!/bin/bash

source .venv/bin/activate
: "${ALLOWED_EMAIL:?export ALLOWED_EMAIL=you@example.com (the Google account that may sign in)}"
uvicorn app.main:app --reload
