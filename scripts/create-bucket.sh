#!/bin/bash
# One-time (idempotent) setup of the private bucket that holds todo image
# attachments, and the wiring that lets the Cloud Run service use it.
# Needs gcloud logged in with permission to create buckets and edit IAM.
set -euo pipefail

PROJECT="${PROJECT:-your-gcp-project-id}"
REGION="${REGION:-us-central1}"      # same region as Cloud Run; inside the Always Free tier
SERVICE="${SERVICE:-now}"
BUCKET="${BUCKET:-${PROJECT}-attachments}"

if ! gcloud storage buckets describe "gs://${BUCKET}" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" \
    --project "$PROJECT" \
    --location "$REGION" \
    --default-storage-class STANDARD \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

# The runtime service account of the Cloud Run service, not a project-wide grant.
SA="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(spec.template.spec.serviceAccountName)')"
if [ -z "$SA" ]; then
  # Default compute service account: PROJECT_NUMBER-compute@developer.gserviceaccount.com
  NUM="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
  SA="${NUM}-compute@developer.gserviceaccount.com"
fi

# Bucket-level binding: objectAdmin here, nothing anywhere else.
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member "serviceAccount:${SA}" --role roles/storage.objectAdmin >/dev/null

# Versioning stays off (default). The 7-day soft delete default is kept as an undo.
gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --update-env-vars "ATTACHMENTS_BUCKET=${BUCKET}"

echo "bucket gs://${BUCKET} ready; service ${SERVICE} runs as ${SA}"
