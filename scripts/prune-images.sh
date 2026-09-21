#!/bin/bash
# Delete every image in the deploy repo except the one the service is running now.
# Each `gcloud run deploy --source` pushes ~70 MB and the free tier is 512 MB; the registry's
# cleanup policy (setup-cost-guards.sh) only runs about daily, so a day of deploys can pass
# the limit. deploy.sh runs this after every deploy. Safe to repeat.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/config.sh   # PROJECT, REGION, SERVICE

REPO_HOST="${REGION}-docker.pkg.dev"
REPO=cloud-run-source-deploy
running="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format='value(spec.template.spec.containers[0].image)')"
keep="${running##*@}"   # sha256:...
[ -n "$keep" ] && [ "$keep" != "$running" ] || { echo "prune-images: can't tell which image is running; leaving all" >&2; exit 0; }

removed=0
while read -r package digest; do
  [ -z "$digest" ] || [ "$digest" = "$keep" ] && continue
  gcloud artifacts docker images delete "$REPO_HOST/$PROJECT/$REPO/$package@$digest" --delete-tags --quiet >/dev/null 2>&1 \
    && removed=$((removed + 1))
done < <(gcloud artifacts docker images list "$REPO_HOST/$PROJECT/$REPO" --format='value(package.basename(),version)' 2>/dev/null)
echo "prune-images: removed $removed old image(s), kept the running one"
