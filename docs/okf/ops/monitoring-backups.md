---
type: Runbook
title: Monitoring and backups
description: Uptime check, alert policies, sync-conflict metric, and Firestore backups (all GCP config, not in code).
tags: [ops, monitoring, backups, gcp]
timestamp: 2026-09-20T00:00:00Z
---
Configured in project `your-gcp-project-id` with gcloud; nothing here is in the repo's code.

- **Uptime check** `now-health`: HTTPS GET `/health` on the Cloud Run host every 5 min ([public route](../api/routes.md)).
- **Alert policies** (channel: `now-app Error Alerts`, a Pub/Sub channel, so no email yet): `now - health check failing`, `now - 5xx responses` (>3 5xx in 5 min on service `now`). The older `now-app - High Error Rate Alert` targets service `now-app` with no 5xx filter and never fires; it is left in place pending removal.
- **Log-based metric** `now_sync_conflicts`: 409/412 responses from service `now` ([sync model](../features/sync-model.md)).
- **Error Reporting** is automatic for `logging.exception` stack traces in Cloud Run logs.
- **Firestore backups:** point-in-time recovery on (7-day window) plus a daily backup schedule with 7-day retention, database `(default)` ([collections](../data/firestore.md)). Restore with `gcloud firestore databases clone` (PITR) or `gcloud firestore databases restore` (backup) into a new database.
- **Secret Manager:** the widget token lives in secret `widget-token`, mounted as env `WIDGET_TOKEN` ([widget](widget.md)).
- **Scheduler job** `now-notify` drives [push reminders](../features/push-reminders.md); a failing job shows in Cloud Scheduler and as 401/403/5xx on `/internal/notify` in the Cloud Run logs.
