#!/bin/bash
# Read-only check that a deployment is wired up. Prints OK / WARN / FAIL per item
# (variable names only, never values) and exits non-zero on any FAIL.
# Run after scripts/init.sh, or any time something misbehaves.
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/config.sh

fails=0
ok()   { printf '  OK    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; fails=$((fails + 1)); }

echo "project=$PROJECT region=$REGION service=$SERVICE"

echo "tools"
for t in gcloud firebase python3; do
  command -v "$t" >/dev/null && ok "$t" || fail "$t not installed"
done
gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q . \
  && ok "gcloud signed in" || fail "gcloud not signed in (gcloud auth login)"

echo "project"
enabled="$(gcloud services list --enabled --project "$PROJECT" --format='value(config.name)' 2>/dev/null)"
for api in run.googleapis.com firestore.googleapis.com identitytoolkit.googleapis.com; do
  grep -qx "$api" <<<"$enabled" && ok "API $api" || fail "API $api not enabled"
done
for api in cloudscheduler.googleapis.com fcm.googleapis.com; do
  grep -qx "$api" <<<"$enabled" && ok "API $api" || warn "API $api not enabled (push reminders need it: scripts/setup-push.sh)"
done
gcloud firestore databases describe --project "$PROJECT" >/dev/null 2>&1 \
  && ok "Firestore database" || fail "no Firestore database"

echo "service"
names="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format='value(spec.template.spec.containers[0].env[].name)' 2>/dev/null)"
if [ -z "$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(metadata.name)' 2>/dev/null)" ]; then
  fail "Cloud Run service $SERVICE not found in $REGION (./deploy.sh)"
else
  ok "Cloud Run service $SERVICE"
  has() { tr ';' '\n' <<<"$names" | grep -qx "$1"; }
  has ALLOWED_EMAIL       && ok "env ALLOWED_EMAIL"       || fail "env ALLOWED_EMAIL missing (the server refuses to start without it)"
  has ATTACHMENTS_BUCKET  && ok "env ATTACHMENTS_BUCKET"  || fail "env ATTACHMENTS_BUCKET missing (scripts/create-bucket.sh; uploads fail without it)"
  has WIDGET_TOKEN        && ok "env WIDGET_TOKEN"        || warn "env WIDGET_TOKEN unset (lock screen widget off)"
  has CALENDAR_TOKEN      && ok "env CALENDAR_TOKEN"      || warn "env CALENDAR_TOKEN unset (calendar feed off: scripts/setup-calendar.sh)"
  has NOTIFY_AUDIENCE && has NOTIFY_CALLER && ok "env NOTIFY_* (reminders)" || warn "NOTIFY_* unset (reminders off: scripts/setup-push.sh)"
  url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)' 2>/dev/null)"
  code="$(curl -s -o /dev/null -w '%{http_code}' "$url/health" 2>/dev/null || true)"
  [ "$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format="value(spec.template.metadata.annotations['run.googleapis.com/cpu-throttling'])" 2>/dev/null)" = "true" ] \
    && ok "request-based billing (CPU throttled between requests)" \
    || fail "always-on CPU is on: about \$30/month with the reminder job (gcloud run services update $SERVICE --cpu-throttling)"
  [ "$code" = "200" ] && ok "GET /health 200" || fail "GET /health returned ${code:-no response}"
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$url/todos/root" 2>/dev/null || true)" = "401" ] \
    && ok "API refuses unauthenticated requests" || fail "API did not answer 401 without a token"
fi
bucket="$(gcloud storage buckets list --project "$PROJECT" --filter="name:${PROJECT}-attachments" --format='value(name)' 2>/dev/null)"
[ -n "$bucket" ] && ok "attachments bucket" || warn "no ${PROJECT}-attachments bucket (scripts/create-bucket.sh)"

echo "cost"
ACCOUNT="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null | sed 's|billingAccounts/||')"
if [ -n "$ACCOUNT" ] && gcloud billing budgets list --billing-account "$ACCOUNT" --project "$PROJECT" --format='value(displayName)' 2>/dev/null | grep -q .; then
  ok "a budget exists on the billing account"
else
  warn "no budget visible (scripts/setup-cost-guards.sh)"
fi
gcloud artifacts repositories describe cloud-run-source-deploy --project "$PROJECT" --location "$REGION" --format='value(cleanupPolicies)' 2>/dev/null | grep -q . \
  && ok "Artifact Registry cleanup policy" || warn "no image cleanup policy on cloud-run-source-deploy (scripts/setup-cost-guards.sh)"

echo "client config"
if [ -f web/config.js ]; then
  grep -q "\"$PROJECT\"" web/config.js && ok "web/config.js projectId matches" || fail "web/config.js does not mention project $PROJECT"
else
  fail "web/config.js missing (scripts/init.sh, or copy web/config.example.js)"
fi
grep -q "\"$PROJECT\"" .firebaserc 2>/dev/null && ok ".firebaserc" || warn ".firebaserc missing or not pointing at $PROJECT (cp .firebaserc.example .firebaserc, or scripts/init.sh)"
grep -q "\"serviceId\": \"$SERVICE\"" firebase.json && ok "firebase.json rewrites to $SERVICE" \
  || warn "firebase.json hosting rewrite does not point at service $SERVICE"

echo
echo "not checkable from here (Firebase console): Authentication > Sign-in method > Google is enabled,"
echo "and your site domain is under Authentication > Settings > Authorized domains."
[ "$fails" -eq 0 ] && echo "doctor: no failures" || { echo "doctor: $fails failure(s)"; exit 1; }
