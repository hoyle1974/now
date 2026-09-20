---
type: Backlog
title: Roadmap and open items
description: What is left to do for fork-friendliness and the zilch-gcp connection, and known loose ends.
tags: [roadmap, fork, zilch, todo]
timestamp: 2026-09-21T01:00:00Z
---
Context: [forking](forking.md), [zilch-gcp](../architecture/zilch-gcp.md). Ordered roughly by value.

**Fork / zilch**
1. **Prove `scripts/init.sh` in a scratch GCP project** with billing (zilch, then `init.sh --push`, then `doctor.sh`). So far only `--dry-run` and read-only calls against the author's project. Unverified: the shape of `firebase apps:list --json`, `apps:create`, `hosting:sites:create`, and step order on an empty project.
2. **Reminders into zilch.** Decision: keep the reminders job script-managed (`setup-push.sh`) for now; its OIDC audience must equal `NOTIFY_AUDIENCE`, and zilch's v2 service URI differs in form from the `status.url` the script uses, so moving it is a separate, testable change. For reference: zilch's `enable_scheduler` job takes `scheduler_schedule` / `scheduler_endpoint` / timezone and signs OIDC as the app service account with audience = service URL. Set them to `*/10 6-23 * * *`, `/internal/notify`, and the owner's timezone, set `NOTIFY_CALLER` to that service account's email, and drop the separate `now-notify` SA from `setup-push.sh`. Still scripted: `roles/firebasecloudmessaging.admin` for the runtime SA, the FCM/installations APIs, the `push_sent.expires_at` TTL. The job's timezone now defaults to the machine's (`SCHEDULE_TZ` / `.now.env` override).
3. **Monitoring into Terraform: code done, not applied.** zilch commit `1f76d72` (pushed) turns its alert into a real 5xx policy, adds a `<app>-health` uptime check and a "health check failing" policy, and an optional `alert_email` channel. A read-only plan against this project's state shows 2 to add, 1 to change, 0 to destroy. Apply it (`terraform apply` from a copy of zilch with `terraform init -backend-config="bucket=your-gcp-project-id-zilch-tfstate" -backend-config="prefix=terraform/state/now-app"` and the vars from `.zilch.config`) only **after step 4**, since these target service `now-app`. Then delete the hand-made `now - health check failing`, `now - 5xx responses`, `now-health` uptime check and the old `now-app - High Error Rate Alert` (already renamed in place by the apply). The log metric `now_sync_conflicts` stays hand-made (app-specific).
4. **Migrate prod from `now` to `now-app`: script ready, not run.** `OLD_SERVICE=now SERVICE=now-app scripts/migrate-service.sh --dry-run`, then without the flag. No data moves. The new service runs as zilch's `now-app@` service account, so the script re-grants what the old one had (bucket, FCM, widget secret) and re-points Hosting and the Scheduler job. The old service stays up until you delete it; update the Scriptable `BASE` to `https://now-app.web.app` first. After it runs, `terraform plan` in zilch may show drift on the service (cpu-throttling annotation, client fields): add them to `ignore_changes`.
5. **Reconcile `.zilch.config` with reality** (see drift in [zilch-gcp](../architecture/zilch-gcp.md)) and decide whether `now` should adopt zilch's storage bucket or keep its own (recommended: keep; zilch's has `force_destroy = true`).
6. **Mention** `now` as a reference app in the zilch README (its commit `4d2eae8` is pushed).
7. **Scrub the author's project id / URLs** from README history and this OKF bundle if the repo goes public (README is already clean; `.firebaserc`, `firebase.json` and OKF still name the project).

**Loose ends found during the review**
- `db.init(memory=...)` parameter is vestigial. `requirements.txt` pins direct dependencies only (no lockfile).
- Every tree read after a write scans the whole `todos` collection (cached per revision); revisit past a few thousand todos.
- zilch `tfplan` file is an untracked leftover in `../zilch-gcp`.
