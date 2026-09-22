#!/bin/bash
# Move the running app from one Cloud Run service to another (e.g. from `now` to the
# service zilch manages, `now-app`) without touching data: Firestore and the bucket
# belong to the project. The old service is left running so nothing breaks (an old
# tab) while you switch; delete it yourself afterwards.
#
#   OLD_SERVICE=now SERVICE=now-app scripts/migrate-service.sh --dry-run
#   OLD_SERVICE=now SERVICE=now-app scripts/migrate-service.sh
#
# What it does, in order (each step is idempotent):
#   1. deploy this tree to the new service, copying ALLOWED_EMAILS (or legacy
#      ALLOWED_EMAIL) / ATTACHMENTS_BUCKET
#   2. bucket grant for the new service's service account  (create-bucket.sh)
#   3. reminders: FCM role, NOTIFY_* env, Scheduler job re-pointed  (setup-push.sh)
#   4. Firebase Hosting rewrite -> new service, then deploy Hosting
#   5. .now.env SERVICE=<new>, then scripts/doctor.sh
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

say "1/5 Deploy to $NEW_SERVICE"
ALLOWED_EMAILS="$ALLOWED_EMAILS" ATTACHMENTS_BUCKET="$BUCKET_VALUE" run ./deploy.sh

say "2/5 Attachments bucket access for $NEW_SERVICE's service account"
BUCKET="${BUCKET_VALUE:-${PROJECT}-attachments}" run scripts/create-bucket.sh

say "3/5 Reminders (FCM role, NOTIFY_* env, Scheduler job -> new URL)"
if svc_env_names "$OLD_SERVICE" | grep -qx NOTIFY_AUDIENCE; then
  run scripts/setup-push.sh
else
  echo "   old service has no reminders configured, skipping"
fi

say "4/5 Firebase Hosting -> $NEW_SERVICE"
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

say "5/5 Point this checkout at $NEW_SERVICE and check"
if [ "$DRY" = 1 ]; then echo "   [dry-run] .now.env SERVICE=$NEW_SERVICE; scripts/doctor.sh"; else
  touch .now.env
  grep -v '^SERVICE=' .now.env > .now.env.tmp || true
  printf 'SERVICE=%s\n' "$NEW_SERVICE" >> .now.env.tmp
  mv .now.env.tmp .now.env
  scripts/doctor.sh
fi

cat <<MSG

Done. $OLD_SERVICE is still running. When you have checked the app (sign in, edit, an image,
a reminder), then delete the old service:
  gcloud run services delete $OLD_SERVICE --region $REGION --project $PROJECT
MSG
