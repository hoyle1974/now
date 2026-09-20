---
type: Runbook
title: Deploy
description: Deploying to Cloud Run.
resource: deploy.sh
tags: [deploy]
timestamp: 2026-09-20T22:00:00Z
---
`./deploy.sh` runs `gcloud run deploy` with `--no-cpu-throttling` (the archive sweep runs after the response; instance-based billing) for `PROJECT`/`REGION`/`SERVICE` resolved by `scripts/lib/config.sh` ([forking](forking.md); here `.now.env` pins `SERVICE=now`). It refuses to run without `web/config.js`. Env vars and secrets already on the service are kept (`ALLOWED_EMAIL` is required and lives there); exporting `ALLOWED_EMAIL` or `ATTACHMENTS_BUCKET` sets them. The image holds only `app/` and `web/` (allow-list `.dockerignore`, runs as non-root); `.gcloudignore` decides what gcloud uploads (it replaces `.gitignore`, so private files are repeated there). `requirements.txt` is pinned; tests need `requirements-dev.txt`. On a client release, bump `APP_VERSION` in `web/app.js` and the `?v=` in `web/index.html` together ([sync model](../features/sync-model.md)). The widget token is an env var on the service ([widget](widget.md)). Image attachments need the bucket: run `scripts/create-bucket.sh` once (creates it, grants the Cloud Run service account `objectAdmin` on that bucket only, sets `ATTACHMENTS_BUCKET` on the service); without it uploads fail ([attachments](../features/attachments.md)). Push reminders need `scripts/setup-push.sh` once (APIs, FCM role, Scheduler job, `NOTIFY_AUDIENCE`/`NOTIFY_CALLER`), and `firebase deploy --only firestore:indexes` for the due-window index, before the first scheduled run ([push reminders](../features/push-reminders.md)).
