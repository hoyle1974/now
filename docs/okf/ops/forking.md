---
type: Runbook
title: Forking and per-deployment config
description: How a fork is set up (zilch for infrastructure, init.sh for the app), and where per-deployment settings live.
resource: scripts/init.sh
tags: [fork, config, zilch, deploy]
timestamp: 2026-09-21T01:00:00Z
---
Two layers. **Infrastructure** comes from [zilch-gcp](https://github.com/hoyle1974/zilch-gcp) (sibling repo `../zilch-gcp`, Terraform): project APIs, Cloud Run, Firestore, Scheduler, monitoring; it writes `.zilch.config`. **The app** is set up by `scripts/init.sh` (`--dry-run` to preview, `--push` to add reminders, `--widget` to create the lock screen widget token secret, `--calendar` for the private [calendar feed](../features/calendar-feed.md) (`scripts/setup-calendar.sh`)) and verified by the read-only `scripts/doctor.sh` (names only, never env values). `init.sh` has only been run as `--dry-run` and against the author's own project.

**Where settings live** (nothing project-specific is hardcoded in code any more):
- `scripts/lib/config.sh` resolves `PROJECT`, `REGION`, `SERVICE` for every script: environment > `.now.env` > `.zilch.config` (`gcp_project_id`, `gcp_region`, `app_name`) > `gcloud config`. Files are parsed, not sourced. No defaults name the author's project.
- `.now.env` (git-ignored; `.now.env.example`): app-side overrides `SERVICE`, `HOSTING_SITE`, `ALLOWED_EMAIL`, `PROJECT`, `REGION`. The service is `now-app`, which is also zilch's `app_name`, so neither `SERVICE` nor `HOSTING_SITE` needs pinning; keep the file only for genuine overrides.
- `web/config.js` (git-ignored; `web/config.example.js`): `window.NOW_CONFIG` = Firebase web config + optional `hostingDomain`. Read by `web/auth.js`; without it the sign-in overlay says so. `deploy.sh` refuses to run without it. The Firebase web config is public by design.
- `.firebaserc` (git-ignored, `.firebaserc.example`) and `firebase.json` (tracked): `init.sh` writes the project, Hosting site and Cloud Run rewrite (`serviceId`, region). Real project ids live only in git-ignored files (`.zilch.config`, `.now.env`, `.firebaserc`, `web/config.js`); docs use `<project-id>` placeholders.
- `ALLOWED_EMAIL` is required ([stack](../architecture/stack.md)); `scripts/scriptable-next-up.js` has a `BASE` placeholder.

**Not scriptable:** enabling Google sign-in and the authorized domain in the Firebase console.

**Migration done (2026-09-20)** with `scripts/migrate-service.sh` (kept as the runbook for any future service move: no data moves; it re-grants IAM for the new service account, re-points Hosting, the Scheduler job and `NOTIFY_AUDIENCE`, and leaves the old service up; delete it yourself once nothing uses its URL). The `now_sync_conflicts` log-metric filter and the widget `BASE` are manual afterwards.

Open items: [roadmap](roadmap.md); relationship to zilch (including the changes made there for this): [zilch-gcp](../architecture/zilch-gcp.md).

