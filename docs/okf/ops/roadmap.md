---
type: Backlog
title: Roadmap and open items
description: What is left to do for fork-friendliness and the zilch-gcp connection, and known loose ends.
tags: [roadmap, fork, zilch, todo]
timestamp: 2026-09-20T23:30:00Z
---
Context: [forking](forking.md), [zilch-gcp](../architecture/zilch-gcp.md). Ordered roughly by value.

**Fork / zilch**
1. **Prove `scripts/init.sh` in a scratch GCP project** with billing (zilch, then `init.sh --push`, then `doctor.sh`). So far only `--dry-run` and read-only calls against the author's project. Unverified: the shape of `firebase apps:list --json`, `apps:create`, `hosting:sites:create`, and step order on an empty project.
2. **Reminders into zilch.** Zilch's `enable_scheduler` job takes `scheduler_schedule` / `scheduler_endpoint` / timezone and signs OIDC as the app service account with audience = service URL. Set them to `*/10 6-23 * * *`, `/internal/notify`, and the owner's timezone, set `NOTIFY_CALLER` to that service account's email, and drop the separate `now-notify` SA from `setup-push.sh`. Still scripted: `roles/firebasecloudmessaging.admin` for the runtime SA, the FCM/installations APIs, the `push_sent.expires_at` TTL. `setup-push.sh` hardcodes `America/Los_Angeles` as default timezone.
3. **Monitoring into Terraform**: uptime check `now-health`, log metric `now_sync_conflicts`, alert policies `health check failing` and `5xx responses`; delete the old `now-app - High Error Rate Alert`; add an email channel (today only Pub/Sub). Zilch's own policy targets service `now-app`.
4. **Migrate prod from `now` to `now-app`** (no data moves; details in [forking](forking.md)). Only worth it once 1-3 are done; until then `.now.env` (`SERVICE=now`) must not be deleted. Alternative: set zilch `app_name=now` and `terraform import` the running service.
5. **Widget token** is still manual (Secret Manager secret `widget-token`, `--update-secrets`). Add an `init.sh --widget` step that generates and stores it.
6. **Reconcile `.zilch.config` with reality** (see drift in [zilch-gcp](../architecture/zilch-gcp.md)) and decide whether `now` should adopt zilch's storage bucket or keep its own (recommended: keep; zilch's has `force_destroy = true`).
7. **Push the zilch commit** (`4d2eae8`, local only) and mention `now` as a reference app in its README.
8. **Scrub the author's project id / URLs** from README history and this OKF bundle if the repo goes public (README is already clean; `.firebaserc`, `firebase.json` and OKF still name the project).

**Loose ends found during the review**
- `db.init(memory=...)` parameter is vestigial. `requirements.txt` pins direct dependencies only (no lockfile).
- Every tree read after a write scans the whole `todos` collection (cached per revision); revisit past a few thousand todos.
- zilch `tfplan` file is an untracked leftover in `../zilch-gcp`.
