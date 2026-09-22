#!/bin/bash

source .venv/bin/activate
: "${ALLOWED_EMAILS:=${ALLOWED_EMAIL:?export ALLOWED_EMAILS=you@example.com;kid@example.com (Google accounts that may sign in)}}"
export ALLOWED_EMAILS
uvicorn app.main:app --reload
