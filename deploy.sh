#!/bin/bash
# Deploy the current tree to Cloud Run. Env vars and secrets already on the
# service (ALLOWED_EMAIL, ATTACHMENTS_BUCKET, WIDGET_TOKEN, NOTIFY_*) are kept.
#
# --no-cpu-throttling: the archive sweep runs after a response is sent (see
# _load_tree in app/main.py) and would crawl if CPU were throttled between requests.
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="${PROJECT:-your-gcp-project-id}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-now}"

args=(--source . --project "$PROJECT" --region "$REGION" --no-cpu-throttling)
# Set these only when exporting them, e.g. ALLOWED_EMAIL=me@example.com ./deploy.sh
env_vars=""
[ -n "${ALLOWED_EMAIL:-}" ] && env_vars+="ALLOWED_EMAIL=${ALLOWED_EMAIL},"
[ -n "${ATTACHMENTS_BUCKET:-}" ] && env_vars+="ATTACHMENTS_BUCKET=${ATTACHMENTS_BUCKET},"
[ -n "$env_vars" ] && args+=(--update-env-vars "${env_vars%,}")

gcloud run deploy "$SERVICE" "${args[@]}"
