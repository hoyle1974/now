#!/bin/bash
# Deploy the current tree to Cloud Run. Env vars and secrets already on the
# service (ALLOWED_EMAILS, ATTACHMENTS_BUCKET, WIDGET_TOKEN, NOTIFY_*) are kept.
# PROJECT / REGION / SERVICE come from scripts/lib/config.sh (.now.env, .zilch.config).
#
# --cpu-throttling (request-based billing): CPU is billed only while a request is being
# served. Never use --no-cpu-throttling: an always-allocated instance is billed around the
# clock (about $30/month; it was measured while the reminder job still ran every 10 minutes). The archive sweep that runs
# after a response (see _load_tree in app/routes/todos.py) simply finishes on the next request.
set -euo pipefail
cd "$(dirname "$0")"
source scripts/lib/config.sh

args=(--source . --project "$PROJECT" --region "$REGION" --cpu-throttling)
# Set these only when exporting them, e.g. ALLOWED_EMAILS='me@example.com;kid@example.com' ./deploy.sh
ALLOWED_EMAILS="${ALLOWED_EMAILS:-${ALLOWED_EMAIL:-$(_cfg .now.env ALLOWED_EMAILS)}}"
ALLOWED_EMAILS="${ALLOWED_EMAILS:-$(_cfg .now.env ALLOWED_EMAIL)}"
if [[ "${ALLOWED_EMAILS:-}" == *,* ]]; then
  echo "error: ALLOWED_EMAILS must not contain a comma - gcloud's --update-env-vars splits" >&2
  echo "on commas, so a comma-separated list would corrupt the env vars. Use ';' to separate" >&2
  echo "multiple emails, e.g. ALLOWED_EMAILS='you@example.com;kid@example.com' ./deploy.sh" >&2
  exit 1
fi
env_vars=""
[ -n "${ALLOWED_EMAILS:-}" ] && env_vars+="ALLOWED_EMAILS=${ALLOWED_EMAILS},"
[ -n "${ATTACHMENTS_BUCKET:-}" ] && env_vars+="ATTACHMENTS_BUCKET=${ATTACHMENTS_BUCKET},"
[ -n "$env_vars" ] && args+=(--update-env-vars "${env_vars%,}")

if [ ! -f web/config.js ]; then
  echo "error: web/config.js is missing (Firebase web config). Run scripts/init.sh, or copy web/config.example.js." >&2
  exit 1
fi

gcloud run deploy "$SERVICE" "${args[@]}"

# Old images pile up ~70 MB per deploy (free tier 512 MB): keep only the one now serving.
scripts/prune-images.sh || echo "warning: image prune failed; the cost check below will say if it matters" >&2

# Rule #1 is zero GCP cost: verify (read-only) that this deploy did not break it.
scripts/cost-check.sh || { echo "deploy finished, but the cost check FAILED. Fix it now." >&2; exit 1; }
