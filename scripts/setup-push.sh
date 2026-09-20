#!/bin/bash
# One-time (idempotent) GCP setup for push reminders: APIs, the FCM send role,
# the Scheduler identity and job, the env vars /internal/notify checks, and the
# Firestore TTL that prunes sent-markers. Needs gcloud logged in with owner-ish
# rights. Read it first; it changes IAM and creates a Scheduler job.
set -euo pipefail

source "$(dirname "$0")/lib/config.sh"   # PROJECT, REGION, SERVICE
JOB="${JOB:-now-notify}"
CALLER_NAME="${CALLER_NAME:-now-notify}"
# Daytime only, every 10 minutes; the 9:00 rule itself uses each device's own timezone.
SCHEDULE="${SCHEDULE:-*/10 6-23 * * *}"
SCHEDULE_TZ="${SCHEDULE_TZ:-America/Los_Angeles}"

gcloud services enable fcm.googleapis.com fcmregistrations.googleapis.com \
  firebaseinstallations.googleapis.com cloudscheduler.googleapis.com --project "$PROJECT"

SA="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(spec.template.spec.serviceAccountName)')"
if [ -z "$SA" ]; then
  NUM="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
  SA="${NUM}-compute@developer.gserviceaccount.com"
fi
# The runtime account may send FCM messages, nothing broader.
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${SA}" --role roles/firebasecloudmessaging.admin --condition=None >/dev/null

# The identity Scheduler signs its OIDC token with. It needs no roles: the app
# verifies the token itself (audience + email), so /internal/notify is closed to
# everyone else, including the signed-in user.
CALLER="${CALLER_NAME}@${PROJECT}.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$CALLER" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$CALLER_NAME" --project "$PROJECT" --display-name "now push scheduler"

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --update-env-vars "NOTIFY_AUDIENCE=${URL},NOTIFY_CALLER=${CALLER}"

if gcloud scheduler jobs describe "$JOB" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
  VERB=update
else
  VERB=create
fi
gcloud scheduler jobs "$VERB" http "$JOB" --project "$PROJECT" --location "$REGION" \
  --schedule "$SCHEDULE" --time-zone "$SCHEDULE_TZ" \
  --uri "${URL}/internal/notify" --http-method POST \
  --oidc-service-account-email "$CALLER" --oidc-token-audience "$URL" \
  --attempt-deadline 60s

# Sent-markers carry expires_at; let Firestore delete them (free).
gcloud firestore fields ttls update expires_at --collection-group=push_sent \
  --enable-ttl --database='(default)' --project "$PROJECT" --async || true

echo "push reminders ready: job ${JOB} (${SCHEDULE} ${SCHEDULE_TZ}) -> ${URL}/internal/notify"
echo "test now with: gcloud scheduler jobs run ${JOB} --location ${REGION} --project ${PROJECT}"
