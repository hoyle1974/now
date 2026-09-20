---
type: Runbook
title: Deploy
description: Deploying to Cloud Run.
resource: deploy.sh
tags: [deploy]
timestamp: 2026-09-20T23:30:00Z
---
`./deploy.sh` runs `gcloud run deploy --source .` with `--no-cpu-throttling` (the archive sweep runs after the response; instance-based billing). `PROJECT`/`REGION`/`SERVICE` come from `scripts/lib/config.sh` ([forking](forking.md)).

- **Refuses to run** without `web/config.js`.
- **Env and secrets** already on the service are kept (`ALLOWED_EMAIL` is required and lives there). Exporting `ALLOWED_EMAIL` or `ATTACHMENTS_BUCKET` sets them. The widget token is a Secret Manager reference ([widget](widget.md)).
- **Image:** only `app/` and `web/` (allow-list `.dockerignore`, `python:3.13-slim`, non-root). `.gcloudignore` decides what gcloud uploads (it replaces `.gitignore`, so private files are repeated there). `requirements.txt` is pinned; tests need `requirements-dev.txt`.
- **Client release:** bump `APP_VERSION` in `web/app.js` and every `?v=` in `web/index.html` together ([sync model](../features/sync-model.md)).
- **One-time setup:**
  - Images: `scripts/create-bucket.sh` (creates the bucket, grants the Cloud Run service account `objectAdmin` on it only, sets `ATTACHMENTS_BUCKET`); without it uploads fail ([attachments](../features/attachments.md)).
  - Reminders: `scripts/setup-push.sh` (APIs, FCM role, Scheduler job, `NOTIFY_AUDIENCE`/`NOTIFY_CALLER`) plus `firebase deploy --only firestore:indexes` for the due-window index, before the first scheduled run ([push reminders](../features/push-reminders.md)).
