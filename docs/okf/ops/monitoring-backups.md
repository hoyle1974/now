---
type: Runbook
title: Monitoring and backups
description: Uptime check, alert policies, sync-conflict metric, and Firestore backups (all GCP config, not in code).
tags: [ops, monitoring, backups, gcp]
timestamp: 2026-09-20T14:00:00Z
---
Configured in project `<project-id>` with gcloud; nothing here is in the repo's code.

- **Managed by zilch Terraform** (`cloud_monitoring.tf`, [zilch-gcp](../architecture/zilch-gcp.md)): uptime check `now-app-health` (HTTPS GET `/health` every 5 min, [public route](../api/routes.md)), alert policies `now-app - health check failing` and `now-app - 5xx responses` (>3 5xx in 5 min), notification channel `now-app Error Alerts` (Pub/Sub, so no email yet: set `alert_email` in `.zilch.config` for email). Change them in zilch, not the console.
- The hand-made `now-health` check and `now - ...` policies for the old service were deleted on 2026-09-20 after the move to `now-app`.
- **Log-based metric** `now_sync_conflicts`: 409/412 responses from service `now-app` (hand-made with gcloud; filter updated at the migration, and must follow any future service rename) ([sync model](../features/sync-model.md)).
- **Error Reporting** is automatic for `logging.exception` stack traces in Cloud Run logs.
- **Firestore backups:** point-in-time recovery on (7-day window) plus a daily backup schedule with 7-day retention, database `(default)` ([collections](../data/firestore.md)). Restore with `gcloud firestore databases clone` (PITR) or `gcloud firestore databases restore` (backup) into a new database.
- **Secret Manager:** the widget token lives in secret `widget-token`, mounted as env `WIDGET_TOKEN` ([widget](widget.md)).
- **Scheduler job** `now-notify` drives [push reminders](../features/push-reminders.md); a failing job shows in Cloud Scheduler and as 401/403/5xx on `/internal/notify` in the Cloud Run logs.
