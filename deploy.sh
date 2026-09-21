#!/bin/bash
# Deploy the current tree to Cloud Run. Env vars and secrets already on the
# service (ALLOWED_EMAIL, ATTACHMENTS_BUCKET, WIDGET_TOKEN, NOTIFY_*) are kept.
# PROJECT / REGION / SERVICE come from scripts/lib/config.sh (.now.env, .zilch.config).
#
# --cpu-throttling (request-based billing): CPU is billed only while a request is being
# served. Never use --no-cpu-throttling: an always-allocated instance is billed around the
# clock (about $30/month; it was measured while the reminder job still ran every 10 minutes). The archive sweep that runs
# after a response (see _load_tree in app/main.py) simply finishes on the next request.
set -euo pipefail
cd "$(dirname "$0")"
source scripts/lib/config.sh

args=(--source . --project "$PROJECT" --region "$REGION" --cpu-throttling)
# Set these only when exporting them, e.g. ALLOWED_EMAIL=me@example.com ./deploy.sh
ALLOWED_EMAIL="${ALLOWED_EMAIL:-$(_cfg .now.env ALLOWED_EMAIL)}"
env_vars=""
[ -n "${ALLOWED_EMAIL:-}" ] && env_vars+="ALLOWED_EMAIL=${ALLOWED_EMAIL},"
[ -n "${ATTACHMENTS_BUCKET:-}" ] && env_vars+="ATTACHMENTS_BUCKET=${ATTACHMENTS_BUCKET},"
[ -n "$env_vars" ] && args+=(--update-env-vars "${env_vars%,}")

if [ ! -f web/config.js ]; then
  echo "error: web/config.js is missing (Firebase web config). Run scripts/init.sh, or copy web/config.example.js." >&2
  exit 1
fi

gcloud run deploy "$SERVICE" "${args[@]}"
