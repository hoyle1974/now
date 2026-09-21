#!/bin/bash
# One-time (idempotent) setup of the private calendar feed: a random token in Secret
# Manager (secret calendar-token), exposed to the Cloud Run service as CALENDAR_TOKEN.
# The feed URL contains the token, so it is written to .calendar-url (git-ignored),
# never printed. The app's More panel also shows it once you are signed in.
#
#   scripts/setup-calendar.sh            # create if missing
#   scripts/setup-calendar.sh --rotate   # new token; the old URL stops working at once
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/config.sh   # PROJECT, REGION, SERVICE

ROTATE=0
[ "${1:-}" = "--rotate" ] && ROTATE=1

if ! gcloud secrets describe calendar-token --project "$PROJECT" >/dev/null 2>&1; then
  openssl rand -hex 24 | tr -d '\n' | gcloud secrets create calendar-token --project "$PROJECT" \
    --replication-policy automatic --data-file=- >/dev/null
  ROTATE=1
elif [ "$ROTATE" = 1 ]; then
  openssl rand -hex 24 | tr -d '\n' | gcloud secrets versions add calendar-token --project "$PROJECT" \
    --data-file=- >/dev/null
fi

SA="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
SA="${SA:-$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')-compute@developer.gserviceaccount.com}"
gcloud secrets add-iam-policy-binding calendar-token --project "$PROJECT" \
  --member "serviceAccount:${SA}" --role roles/secretmanager.secretAccessor >/dev/null

# A new revision picks up the latest secret version.
gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --update-secrets CALENDAR_TOKEN=calendar-token:latest >/dev/null

HOSTING_SITE="${HOSTING_SITE:-$(_cfg .now.env HOSTING_SITE)}"
HOSTING_SITE="${HOSTING_SITE:-$(_cfg .zilch.config app_name)}"
HOSTING_SITE="${HOSTING_SITE:-$SERVICE}"
TOKEN="$(gcloud secrets versions access latest --secret calendar-token --project "$PROJECT")"
printf 'https://%s.web.app/calendar/%s.ics\n' "$HOSTING_SITE" "$TOKEN" > .calendar-url
chmod 600 .calendar-url
echo "calendar feed ready (secret calendar-token, env CALENDAR_TOKEN on $SERVICE)."
echo "link saved to .calendar-url; the app's More panel shows Subscribe / Copy link."
[ "$ROTATE" = 1 ] && echo "token changed: re-subscribe any calendar that used the old link."
