---
type: Runbook
title: Deploy
description: Deploying to Cloud Run.
resource: deploy.sh
tags: [deploy]
timestamp: 2026-09-19T12:00:00Z
---
`./deploy.sh` runs `gcloud run deploy now --source . --region us-central1`. On a client release, bump `APP_VERSION` in `web/app.js` and the `?v=` in `web/index.html` together ([sync model](../features/sync-model.md)). The widget token is an env var on the service ([widget](widget.md)). Image attachments need the bucket: run `scripts/create-bucket.sh` once (creates it, grants the Cloud Run service account `objectAdmin` on that bucket only, sets `ATTACHMENTS_BUCKET` on the service); without it uploads fail ([attachments](../features/attachments.md)).
