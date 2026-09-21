---
type: Runbook
title: Deploy
description: Deploying to Cloud Run.
resource: deploy.sh
tags: [deploy]
timestamp: 2026-09-21T03:00:00Z
---
`./deploy.sh` ends with the read-only `scripts/cost-check.sh` ([principles](../principles.md)) and fails loudly if the deploy left anything billable. It runs `gcloud run deploy --source .` with `--cpu-throttling` (request-based billing). **Never `--no-cpu-throttling`**: an always-allocated instance is billed 24/7 (measured while the reminder tick still ran every 10 minutes: 2026-09-21: 60 of 60 minutes per hour, about $30/month on 1 vCPU / 512Mi; the free tier is 240k vCPU-s per month). The post-response archive sweep may crawl between requests, but the next request and the 15-minute lease cover it. **Max instances is 1** (`gcloud run services update now-app --max-instances 1`, set 2026-09-21): a personal app never needs more, and it hard-caps compute cost against abuse; terraform does not manage it. zilch pins the same (`cpu_idle = true`, [zilch-gcp](../architecture/zilch-gcp.md)). Check: `gcloud run services describe <service> --format="value(spec.template.metadata.annotations['run.googleapis.com/cpu-throttling'])"` must print `true`. `PROJECT`/`REGION`/`SERVICE` come from `scripts/lib/config.sh` ([forking](forking.md)).

- **Refuses to run** without `web/config.js`.
- **Env and secrets** already on the service are kept (`ALLOWED_EMAIL` is required and lives there). Exporting `ALLOWED_EMAIL` or `ATTACHMENTS_BUCKET` sets them. The widget token is a Secret Manager reference ([widget](widget.md)).
- **Image:** only `app/` and `web/` (allow-list `.dockerignore`, `python:3.13-slim`, non-root). `.gcloudignore` decides what gcloud uploads (it replaces `.gitignore`, so private files are repeated there). `requirements.txt` is pinned; tests need `requirements-dev.txt`.
- **Dependencies:** `requirements.in` lists direct deps; `requirements.txt` is the compiled lock the Dockerfile installs (`uv pip compile requirements.in -o requirements.txt --python-version 3.13 --universal`). Re-compile to upgrade.
- **Client release:** bump `APP_VERSION` in `web/app.js` and every `?v=` in `web/index.html` together (this also versions the service worker and its cache) ([sync model](../features/sync-model.md)).
- **One-time setup:**
  - Images: `scripts/create-bucket.sh` (creates the bucket, grants the Cloud Run service account `objectAdmin` on it only, sets `ATTACHMENTS_BUCKET`); without it uploads fail ([attachments](../features/attachments.md)).
  - Cost guards: `scripts/setup-cost-guards.sh` (also run by `init.sh`, idempotent, `--dry-run`): Artifact Registry cleanup policy keeping only the newest image per package (`KEEP_IMAGES`, default 1: single user, always on latest; roll back by redeploying an older commit) in `cloud-run-source-deploy` (each source deploy pushes ~70 MB; free tier 0.5 GiB) and a monthly budget `<service> monthly budget` (`BUDGET_USD`, default 5; alerts at 50% and 100% actual and 100% forecast, emailed to billing account admins; needs Billing Account Administrator/Costs Manager, and the script says so if it is missing). `doctor.sh` warns when either is missing and fails if CPU is always-on.
  - Reminders: `scripts/setup-push.sh` (APIs, FCM role, Scheduler job, `NOTIFY_AUDIENCE`/`NOTIFY_CALLER`) plus `firebase deploy --only firestore:indexes` for the due-window index, before the first scheduled run ([push reminders](../features/push-reminders.md)).
