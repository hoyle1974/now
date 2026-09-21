#!/bin/bash
# One-time (idempotent) GCP setup for push reminders: APIs, the FCM send role,
# the Scheduler identity and daily digest job, the Cloud Tasks queue that carries the
# 1-hour heads-ups, the env vars /internal/notify checks, and the Firestore TTL that
# prunes sent-markers. Needs gcloud logged in with owner-ish
# rights. Read it first; it changes IAM and creates a Scheduler job.
set -euo pipefail

source "$(dirname "$0")/lib/config.sh"   # PROJECT, REGION, SERVICE
JOB="${JOB:-now-notify}"
QUEUE="${QUEUE:-now-reminders}"
CALLER_NAME="${CALLER_NAME:-now-notify}"
# One digest a day at 9:00. Each device's own timezone only decides which day "today" is.
SCHEDULE="${SCHEDULE:-0 9 * * *}"
# Timezone the 9:00 is in: SCHEDULE_TZ, else .now.env, else this machine'"'"'s, else UTC.
SCHEDULE_TZ="${SCHEDULE_TZ:-$(_cfg .now.env SCHEDULE_TZ)}"
SCHEDULE_TZ="${SCHEDULE_TZ:-$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')}"
SCHEDULE_TZ="${SCHEDULE_TZ:-UTC}"

gcloud services enable fcm.googleapis.com fcmregistrations.googleapis.com \
  firebaseinstallations.googleapis.com cloudscheduler.googleapis.com cloudtasks.googleapis.com --project "$PROJECT"

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

# Heads-up queue: the app enqueues one task per timed todo (app/tasks.py); at most 3 tries,
# and the handler is idempotent (sent-markers). The runtime account may only add tasks to
# this queue, and act as the caller identity so the task's OIDC token verifies.
gcloud tasks queues describe "$QUEUE" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1 || \
  gcloud tasks queues create "$QUEUE" --project "$PROJECT" --location "$REGION" --max-attempts 3 --min-backoff 30s
gcloud tasks queues add-iam-policy-binding "$QUEUE" --project "$PROJECT" --location "$REGION" \
  --member "serviceAccount:${SA}" --role roles/cloudtasks.enqueuer >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$CALLER" --project "$PROJECT" \
  --member "serviceAccount:${SA}" --role roles/iam.serviceAccountUser >/dev/null

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --update-env-vars "NOTIFY_AUDIENCE=${URL},NOTIFY_CALLER=${CALLER},REMINDER_QUEUE=projects/${PROJECT}/locations/${REGION}/queues/${QUEUE}"

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

echo "push reminders ready: job ${JOB} (${SCHEDULE} ${SCHEDULE_TZ}) -> ${URL}/internal/notify; heads-ups via queue ${QUEUE}"
echo "test now with: gcloud scheduler jobs run ${JOB} --location ${REGION} --project ${PROJECT}"
