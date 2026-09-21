#!/bin/bash
# Idempotent cost guards for a personal deployment:
#   1. Artifact Registry cleanup policy: every `gcloud run deploy --source` pushes a ~70 MB
#      image into repo cloud-run-source-deploy; the free tier is 0.5 GiB, so keep only the
#      newest few per package.
#   2. A monthly budget on this project with email alerts (billing account admins get them).
#
#   scripts/setup-cost-guards.sh             # both
#   BUDGET_USD=10 scripts/setup-cost-guards.sh
#   scripts/setup-cost-guards.sh --dry-run   # print, change nothing
#
# The budget step needs a role on the billing account (Billing Account Administrator or
# Costs Manager); if you lack it, the script says so and the registry step still runs.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/config.sh   # PROJECT, REGION

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
BUDGET_USD="${BUDGET_USD:-$(_cfg .now.env BUDGET_USD)}"
BUDGET_USD="${BUDGET_USD:-1}"   # rule #1 is zero cost: any real spend should page you
KEEP="${KEEP_IMAGES:-1}"   # single user, always on latest: no rollback images
REPO=cloud-run-source-deploy
BUDGET_NAME="${SERVICE} monthly budget"

run() { if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }

echo "== 1/3 Artifact Registry: keep the newest $KEEP images per package in $REPO"
if gcloud artifacts repositories describe "$REPO" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
  policy="$(mktemp)"
  cat > "$policy" <<JSON
[
  {"name": "keep-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": $KEEP}},
  {"name": "delete-older", "action": {"type": "Delete"}, "condition": {"tagState": "any"}}
]
JSON
  run gcloud artifacts repositories set-cleanup-policies "$REPO" --project "$PROJECT" --location "$REGION" \
    --policy "$policy" --no-dry-run
  rm -f "$policy"
else
  echo "   repository $REPO not found in $REGION yet (it appears after the first ./deploy.sh); rerun then"
fi

echo "== 2/3 Budget: ${BUDGET_USD} USD per month on project $PROJECT"
ACCOUNT="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null | sed 's|billingAccounts/||')"
if [ -z "$ACCOUNT" ]; then
  echo "   project has no billing account (or you cannot see it); skipping the budget" >&2
  exit 0
fi
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
run gcloud services enable billingbudgets.googleapis.com --project "$PROJECT"
existing=""
if [ "$DRY" = 0 ]; then
  existing="$(gcloud billing budgets list --billing-account "$ACCOUNT" --project "$PROJECT" \
    --filter "displayName=\"$BUDGET_NAME\"" --format 'value(name)' 2>/dev/null || true)"
fi
# Alerts at 1%, 50% and 100% of actual spend and when 100% is forecast. Emails go to the billing
# account's admins; every alert is also published to a Pub/Sub topic (step 3 pushes it to your phone).
TOPIC="${SERVICE}-budget-alerts"
if [ -n "$existing" ]; then
  echo "   budget \"$BUDGET_NAME\" exists, leaving its amount alone (edit it in the console, or delete it and rerun)"
else
  if ! run gcloud billing budgets create --billing-account "$ACCOUNT" --project "$PROJECT" \
      --display-name "$BUDGET_NAME" --budget-amount "${BUDGET_USD}USD" \
      --filter-projects "projects/${NUMBER}" \
      --threshold-rule percent=0.01 --threshold-rule percent=0.5 --threshold-rule percent=1.0 \
      --threshold-rule percent=1.0,basis=forecasted-spend; then
    echo "   could not create the budget: you probably lack Billing Account Administrator/Costs Manager on the billing account." >&2
    echo "   Create it in the console (Billing > Budgets & alerts) or ask the billing admin; nothing else was affected." >&2
    exit 1
  fi
  existing="$(gcloud billing budgets list --billing-account "$ACCOUNT" --project "$PROJECT" \
    --filter "displayName=\"$BUDGET_NAME\"" --format 'value(name)' 2>/dev/null || true)"
  echo "budget ready: ${BUDGET_USD} USD/month, emails at 1% / 50% / 100% actual and 100% forecast"
fi

echo "== 3/3 Push alert: budget -> Pub/Sub topic $TOPIC -> POST /internal/budget-alert -> FCM to your devices"
# Needs scripts/setup-push.sh to have run first (the caller identity and the service URL).
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)' 2>/dev/null || true)"
CALLER="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(spec.template.spec.containers[0].env[].name,spec.template.spec.containers[0].env[].value)' 2>/dev/null \
  | tr ';\t' '\n\n' | grep -m1 'iam.gserviceaccount.com' || true)"
if [ -z "$URL" ] || [ -z "$CALLER" ]; then
  echo "   service or NOTIFY_CALLER not found: run ./deploy.sh and scripts/setup-push.sh first, then rerun this" >&2
  exit 0
fi
run gcloud services enable pubsub.googleapis.com --project "$PROJECT"
gcloud pubsub topics describe "$TOPIC" --project "$PROJECT" >/dev/null 2>&1 || run gcloud pubsub topics create "$TOPIC" --project "$PROJECT"
# Pub/Sub signs its push requests as the caller identity; it needs permission to mint that token.
run gcloud iam service-accounts add-iam-policy-binding "$CALLER" --project "$PROJECT" \
  --member "serviceAccount:service-${NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role roles/iam.serviceAccountTokenCreator >/dev/null
SUB="${SERVICE}-budget-push"
if gcloud pubsub subscriptions describe "$SUB" --project "$PROJECT" >/dev/null 2>&1; then VERB=update; else VERB=create; fi
if [ "$VERB" = create ]; then
  run gcloud pubsub subscriptions create "$SUB" --project "$PROJECT" --topic "$TOPIC" \
    --push-endpoint "${URL}/internal/budget-alert" --push-auth-service-account "$CALLER" --push-auth-token-audience "$URL" \
    --ack-deadline 30 --min-retry-delay 60s --max-retry-delay 600s
else
  run gcloud pubsub subscriptions update "$SUB" --project "$PROJECT" \
    --push-endpoint "${URL}/internal/budget-alert" --push-auth-service-account "$CALLER" --push-auth-token-audience "$URL"
fi
[ -n "$existing" ] && run gcloud billing budgets update "$existing" --billing-account "$ACCOUNT" \
  --notifications-rule-pubsub-topic "projects/${PROJECT}/topics/${TOPIC}"
echo "push alert ready. Test end to end: gcloud pubsub topics publish $TOPIC --project $PROJECT --message '{}'  (a routine message: nothing is pushed, the route just answers 200)"
