#!/bin/bash
# Move the running app from one Cloud Run service to another (e.g. from `now` to the
# service zilch manages, `now-app`) without touching data: Firestore and the bucket
# belong to the project. The old service is left running so nothing breaks (an old
# widget URL, an open tab) while you switch; delete it yourself afterwards.
#
#   OLD_SERVICE=now SERVICE=now-app scripts/migrate-service.sh --dry-run
#   OLD_SERVICE=now SERVICE=now-app scripts/migrate-service.sh
#
# What it does, in order (each step is idempotent):
#   1. deploy this tree to the new service, copying ALLOWED_EMAILS (or legacy
#      ALLOWED_EMAIL) / ATTACHMENTS_BUCKET
#   2. bucket grant for the new service's service account  (create-bucket.sh)
#   3. reminders: FCM role, NOTIFY_* env, Scheduler job re-pointed  (setup-push.sh)
#   4. widget secret: access + secret reference, if the old service has WIDGET_TOKEN
#   5. Firebase Hosting rewrite -> new service, then deploy Hosting
#   6. .now.env SERVICE=<new>, then scripts/doctor.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
OLD_SERVICE="${OLD_SERVICE:?set OLD_SERVICE (the service that runs today)}"
NEW_SERVICE="${SERVICE:?set SERVICE (the service to move to)}"
[ "$OLD_SERVICE" != "$NEW_SERVICE" ] || { echo "OLD_SERVICE and SERVICE are the same" >&2; exit 1; }
SERVICE="$NEW_SERVICE" source scripts/lib/config.sh   # PROJECT, REGION, SERVICE=new

say() { printf '\n== %s\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }
svc_env_names() { gcloud run services describe "$1" --project "$PROJECT" --region "$REGION" \
  --format='value(spec.template.spec.containers[0].env[].name)' 2>/dev/null | tr ';' '\n'; }
svc_env_value() { gcloud run services describe "$1" --project "$PROJECT" --region "$REGION" \
  --format=json 2>/dev/null | python3 -c '
import json, sys
name = sys.argv[1]
for e in json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env", []):
    if e["name"] == name and "value" in e:
        print(e["value"])' "$2"; }

echo "project=$PROJECT region=$REGION  $OLD_SERVICE -> $NEW_SERVICE"
gcloud run services describe "$OLD_SERVICE" --project "$PROJECT" --region "$REGION" >/dev/null \
  || { echo "old service $OLD_SERVICE not found" >&2; exit 1; }
gcloud run services describe "$NEW_SERVICE" --project "$PROJECT" --region "$REGION" >/dev/null 2>&1 \
  || echo "note: $NEW_SERVICE does not exist yet; deploy will create it (zilch normally creates it first)"

ALLOWED_EMAILS="$(svc_env_value "$OLD_SERVICE" ALLOWED_EMAILS)"
ALLOWED_EMAILS="${ALLOWED_EMAILS:-$(svc_env_value "$OLD_SERVICE" ALLOWED_EMAIL)}"
BUCKET_VALUE="$(svc_env_value "$OLD_SERVICE" ATTACHMENTS_BUCKET)"
[ -n "$ALLOWED_EMAILS" ] || { echo "old service has no ALLOWED_EMAILS/ALLOWED_EMAIL; set it first" >&2; exit 1; }
[ -n "$BUCKET_VALUE" ] || echo "note: old service has no ATTACHMENTS_BUCKET; create-bucket.sh will set the default"

say "1/6 Deploy to $NEW_SERVICE"
ALLOWED_EMAILS="$ALLOWED_EMAILS" ATTACHMENTS_BUCKET="$BUCKET_VALUE" run ./deploy.sh

say "2/6 Attachments bucket access for $NEW_SERVICE's service account"
BUCKET="${BUCKET_VALUE:-${PROJECT}-attachments}" run scripts/create-bucket.sh

say "3/6 Reminders (FCM role, NOTIFY_* env, Scheduler job -> new URL)"
if svc_env_names "$OLD_SERVICE" | grep -qx NOTIFY_AUDIENCE; then
  run scripts/setup-push.sh
else
  echo "   old service has no reminders configured, skipping"
fi

say "4/6 Widget token"
if svc_env_names "$OLD_SERVICE" | grep -qx WIDGET_TOKEN; then
  SA="$(gcloud run services describe "$NEW_SERVICE" --project "$PROJECT" --region "$REGION" \
    --format 'value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
  SA="${SA:-$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')-compute@developer.gserviceaccount.com}"
  run gcloud secrets add-iam-policy-binding widget-token --project "$PROJECT" \
    --member "serviceAccount:${SA}" --role roles/secretmanager.secretAccessor
  run gcloud run services update "$NEW_SERVICE" --project "$PROJECT" --region "$REGION" \
    --update-secrets WIDGET_TOKEN=widget-token:latest
else
  echo "   old service has no WIDGET_TOKEN, skipping"
fi

say "5/6 Firebase Hosting -> $NEW_SERVICE"
if [ "$DRY" = 1 ]; then echo "   [dry-run] firebase.json rewrite serviceId=$NEW_SERVICE; firebase deploy --only hosting"; else
  python3 - "$NEW_SERVICE" "$REGION" <<'PY'
import json, sys
service, region = sys.argv[1:]
cfg = json.load(open("firebase.json"))
cfg["hosting"]["rewrites"] = [{"source": "**", "run": {"serviceId": service, "region": region}}]
json.dump(cfg, open("firebase.json", "w"), indent=2); open("firebase.json", "a").write("\n")
PY
  firebase deploy --only hosting --project "$PROJECT"
fi

say "6/6 Point this checkout at $NEW_SERVICE and check"
if [ "$DRY" = 1 ]; then echo "   [dry-run] .now.env SERVICE=$NEW_SERVICE; scripts/doctor.sh"; else
  touch .now.env
  grep -v '^SERVICE=' .now.env > .now.env.tmp || true
  printf 'SERVICE=%s\n' "$NEW_SERVICE" >> .now.env.tmp
  mv .now.env.tmp .now.env
  scripts/doctor.sh
fi

cat <<MSG

Done. $OLD_SERVICE is still running. When you have checked the app (sign in, edit, an image,
a reminder), then:
  - iOS widget: set BASE in Scriptable to https://<your-site>.web.app (survives service renames)
  - delete the old service:  gcloud run services delete $OLD_SERVICE --region $REGION --project $PROJECT
MSG
