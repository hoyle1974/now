---
type: Concept
title: How now relates to zilch-gcp
description: What zilch-gcp provisions, what this repo owns, where they overlap or have drifted, and which files connect them.
resource: .zilch.config
tags: [zilch, terraform, infrastructure, config]
timestamp: 2026-09-20T09:00:00Z
---
`now` was built on infrastructure from **zilch-gcp**, the author's own Terraform framework (sibling checkout `../zilch-gcp`, github.com/hoyle1974/zilch-gcp, MIT). `now` is its only real user. Zilch owns *infrastructure*; `now` owns *the app and its wiring*.

**Connection points**
- `.zilch.config` (git-ignored, written by zilch's `cli.py`): `gcp_project_id`, `gcp_region`, `app_name` are read by `scripts/lib/config.sh` as fallbacks for `PROJECT`, `REGION`, `SERVICE`. Unknown keys are ignored by zilch, but the file is zilch-generated, so `now`'s own overrides live in `.now.env` instead ([forking](../ops/forking.md)).
- Zilch names the Cloud Run service `app_name` (= `now-app`). Since 2026-09-20 the app runs **there**: `scripts/migrate-service.sh` deployed it to zilch's service (runtime identity: zilch's `now-app@` service account, re-granted bucket, FCM, widget-secret access). The old service `now` is still running only for an old widget URL; delete it once the Scriptable `BASE` is `https://now-app.web.app`.
- Zilch's `main.tf` ignores changes to the Cloud Run image **and env** (`lifecycle.ignore_changes`, commit `4d2eae8` in zilch), so `terraform apply` cannot strip `ALLOWED_EMAIL`, `WIDGET_TOKEN`, `NOTIFY_*`, `ATTACHMENTS_BUCKET`. Cost: `ZILCH_*` env vars are only written at service creation. The `now` app reads none of them.
- Zilch's optional storage bucket is now created private (public access prevention, uniform access). `now` does not use it: `scripts/create-bucket.sh` makes its own `<project>-attachments` bucket with a bucket-scoped grant and no `force_destroy`.

**Who creates what today**
| Thing | Made by |
|---|---|
| Project APIs, Firestore database (PITR pinned on), the `now-app` Cloud Run service shell, its service account, monitoring (uptime check, alert policies, channel), budget topic | zilch (Terraform; remote state `gs://your-gcp-project-id-zilch-tfstate`, prefix `terraform/state/now-app`) |
| The running code, env vars and `widget-token` secret reference on `now-app` | `deploy.sh`, `setup-push.sh`, `init.sh --widget`, `migrate-service.sh` (zilch ignores image, env, gcloud client fields) |
| Attachments bucket | `scripts/create-bucket.sh` |
| Reminders: Scheduler job, `now-notify` service account, FCM role, `push_sent` TTL | `scripts/setup-push.sh` (zilch has a generic `enable_scheduler` job; unused) |
| Firebase web app, Hosting site, Google sign-in provider | Firebase console / `scripts/init.sh` (sign-in is console-only) |
| Log metric `now_sync_conflicts` | by hand, gcloud ([monitoring](../ops/monitoring-backups.md)) |

**Known drift:** the local `.zilch.config` says `enable_cloud_storage`, `enable_firebase_auth` and `enable_scheduler` are `false`, `enable_monitoring=true`, `allow_unauthenticated_access=true` (the app authenticates itself, [auth](stack.md)). Applying zilch: from a scratch copy of the `.tf` files, `terraform init -backend-config="bucket=your-gcp-project-id-zilch-tfstate" -backend-config="prefix=terraform/state/now-app"`, vars from `.zilch.config` (the zilch checkout's own `terraform.tfvars` is for a different project), `plan` before `apply`. As of 2026-09-20 the plan is clean.
