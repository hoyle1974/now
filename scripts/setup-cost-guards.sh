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
BUDGET_USD="${BUDGET_USD:-5}"
KEEP="${KEEP_IMAGES:-3}"
REPO=cloud-run-source-deploy
BUDGET_NAME="${SERVICE} monthly budget"

run() { if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }

echo "== 1/2 Artifact Registry: keep the newest $KEEP images per package in $REPO"
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

echo "== 2/2 Budget: ${BUDGET_USD} USD per month on project $PROJECT"
ACCOUNT="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null | sed 's|billingAccounts/||')"
if [ -z "$ACCOUNT" ]; then
  echo "   project has no billing account (or you cannot see it); skipping the budget" >&2
  exit 0
fi
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
run gcloud services enable billingbudgets.googleapis.com --project "$PROJECT"
if [ "$DRY" = 0 ]; then
  existing="$(gcloud billing budgets list --billing-account "$ACCOUNT" --project "$PROJECT" \
    --filter "displayName=\"$BUDGET_NAME\"" --format 'value(name)' 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "   budget \"$BUDGET_NAME\" exists, leaving it (edit it in the console, or delete it and rerun)"
    exit 0
  fi
fi
# Alerts at 50% and 100% of actual spend and when 100% is forecast; the default recipients
# are the billing account's admins/users, so no Pub/Sub or webhook is needed.
if ! run gcloud billing budgets create --billing-account "$ACCOUNT" --project "$PROJECT" \
    --display-name "$BUDGET_NAME" --budget-amount "${BUDGET_USD}USD" \
    --filter-projects "projects/${NUMBER}" \
    --threshold-rule percent=0.5 --threshold-rule percent=1.0 \
    --threshold-rule percent=1.0,basis=forecasted-spend; then
  echo "   could not create the budget: you probably lack Billing Account Administrator/Costs Manager on the billing account." >&2
  echo "   Create it in the console (Billing > Budgets & alerts) or ask the billing admin; nothing else was affected." >&2
  exit 1
fi
echo "budget ready: ${BUDGET_USD} USD/month, emails at 50% / 100% actual and 100% forecast"
