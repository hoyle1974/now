---
type: Runbook
title: Forking and per-deployment config
description: How a fork is set up (zilch for infrastructure, init.sh for the app), and where per-deployment settings live.
resource: scripts/init.sh
tags: [fork, config, zilch, deploy]
timestamp: 2026-09-20T23:00:00Z
---
Two layers. **Infrastructure** comes from [zilch-gcp](https://github.com/hoyle1974/zilch-gcp) (sibling repo `../zilch-gcp`, Terraform): project APIs, Cloud Run, Firestore, Scheduler, monitoring; it writes `.zilch.config`. **The app** is set up by `scripts/init.sh` (`--dry-run` to preview, `--push` to add reminders) and verified by the read-only `scripts/doctor.sh` (names only, never env values). `init.sh` has only been run as `--dry-run` and against the author's own project.

**Where settings live** (nothing project-specific is hardcoded in code any more):
- `scripts/lib/config.sh` resolves `PROJECT`, `REGION`, `SERVICE` for every script: environment > `.now.env` > `.zilch.config` (`gcp_project_id`, `gcp_region`, `app_name`) > `gcloud config`. Files are parsed, not sourced. No defaults name the author's project.
- `.now.env` (git-ignored; `.now.env.example`): app-side overrides `SERVICE`, `HOSTING_SITE`, `ALLOWED_EMAIL`, `PROJECT`, `REGION`. Needed because zilch names the service `app_name` (`now-app`) while the running service is `now`; the author's file pins `SERVICE=now`. **Deleting it would make `deploy.sh` target `now-app`.**
- `web/config.js` (git-ignored; `web/config.example.js`): `window.NOW_CONFIG` = Firebase web config + optional `hostingDomain`. Read by `web/auth.js`; without it the sign-in overlay says so. `deploy.sh` refuses to run without it. The Firebase web config is public by design.
- `.firebaserc` / `firebase.json` (tracked): `init.sh` rewrites the project, Hosting site and Cloud Run rewrite (`serviceId`, region).
- `ALLOWED_EMAIL` is required ([stack](../architecture/stack.md)); `scripts/scriptable-next-up.js` has a `BASE` placeholder.

**Not scriptable:** enabling Google sign-in and the authorized domain in the Firebase console.

**Migrating the author's prod from service `now` to zilch's `now-app`** (deliberately not done): no data moves (Firestore and the bucket belong to the project). Deploy to `now-app`, then repoint the Hosting rewrite, the widget `BASE`, the Scheduler URI and `NOTIFY_AUDIENCE`, re-set the env vars/secret, delete `now`. Changing `SERVICE` in `.now.env` plus `firebase.json` covers the scripts; the widget URL and Scheduler job are manual.

Open items: [roadmap](roadmap.md); relationship to zilch: [zilch-gcp](../architecture/zilch-gcp.md).

zilch changes made for this (see its wiki): `ignore_changes` on the Cloud Run image and env so `terraform apply` cannot revert a deploy, and a hardened bucket (public access prevention, uniform access).
