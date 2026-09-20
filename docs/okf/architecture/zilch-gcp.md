---
type: Concept
title: How now relates to zilch-gcp
description: What zilch-gcp provisions, what this repo owns, where they overlap or have drifted, and which files connect them.
resource: .zilch.config
tags: [zilch, terraform, infrastructure, config]
timestamp: 2026-09-20T23:00:00Z
---
`now` was built on infrastructure from **zilch-gcp**, the author's own Terraform framework (sibling checkout `../zilch-gcp`, github.com/hoyle1974/zilch-gcp, MIT). `now` is its only real user. Zilch owns *infrastructure*; `now` owns *the app and its wiring*.

**Connection points**
- `.zilch.config` (git-ignored, written by zilch's `cli.py`): `gcp_project_id`, `gcp_region`, `app_name` are read by `scripts/lib/config.sh` as fallbacks for `PROJECT`, `REGION`, `SERVICE`. Unknown keys are ignored by zilch, but the file is zilch-generated, so `now`'s own overrides live in `.now.env` instead ([forking](../ops/forking.md)).
- Zilch names the Cloud Run service `app_name` (= `now-app`); the running service is **`now`**, deployed with `gcloud run deploy`, so `.now.env` pins `SERVICE=now`. Zilch's own `now-app` service is an idle `hello` placeholder.
- Zilch's `main.tf` ignores changes to the Cloud Run image **and env** (`lifecycle.ignore_changes`, commit `4d2eae8` in zilch), so `terraform apply` cannot strip `ALLOWED_EMAIL`, `WIDGET_TOKEN`, `NOTIFY_*`, `ATTACHMENTS_BUCKET`. Cost: `ZILCH_*` env vars are only written at service creation. The `now` app reads none of them.
- Zilch's optional storage bucket is now created private (public access prevention, uniform access). `now` does not use it: `scripts/create-bucket.sh` makes its own `<project>-attachments` bucket with a bucket-scoped grant and no `force_destroy`.

**Who creates what today**
| Thing | Made by |
|---|---|
| Project APIs, Firestore database, Cloud Run placeholder `now-app`, service account, billing budget, zilch alert policy | zilch (Terraform) |
| Real Cloud Run service `now`, its env vars and `widget-token` secret | `deploy.sh`, `gcloud`, by hand ([widget](../ops/widget.md)) |
| Attachments bucket | `scripts/create-bucket.sh` |
| Reminders: Scheduler job, `now-notify` service account, FCM role, `push_sent` TTL | `scripts/setup-push.sh` (zilch has a generic `enable_scheduler` job; unused) |
| Firebase web app, Hosting site, Google sign-in provider | Firebase console / `scripts/init.sh` (sign-in is console-only) |
| Uptime check, log metric, real alert policies | by hand ([monitoring](../ops/monitoring-backups.md)) |

**Known drift:** the local `.zilch.config` says `enable_cloud_storage`, `enable_firebase_auth` and `enable_scheduler` are `false`, `enable_monitoring=true`, `allow_unauthenticated_access=true` (the app authenticates itself, [auth](stack.md)). Do not "fix" these by re-running zilch without reading [roadmap](../ops/roadmap.md) first.
