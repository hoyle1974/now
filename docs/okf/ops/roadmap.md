---
type: Backlog
title: Roadmap and open items
description: What is left to do for fork-friendliness and the zilch-gcp connection, and known loose ends.
tags: [roadmap, fork, zilch, todo]
timestamp: 2026-09-20T14:00:00Z
---
Context: [forking](forking.md), [zilch-gcp](../architecture/zilch-gcp.md). Ordered roughly by value.

**Fork / zilch**
1. **Prove `scripts/init.sh` in a scratch GCP project** with billing (zilch, then `init.sh --push`, then `doctor.sh`). So far only `--dry-run` and read-only calls against the author's project. Unverified: the shape of `firebase apps:list --json`, `apps:create`, `hosting:sites:create`, and step order on an empty project.
2. **Reminders into zilch.** Decision: keep the reminders job script-managed (`setup-push.sh`) for now; its OIDC audience must equal `NOTIFY_AUDIENCE`, and zilch's v2 service URI differs in form from the `status.url` the script uses, so moving it is a separate, testable change. For reference: zilch's `enable_scheduler` job takes `scheduler_schedule` / `scheduler_endpoint` / timezone and signs OIDC as the app service account with audience = service URL. Set them to `*/10 6-23 * * *`, `/internal/notify`, and the owner's timezone, set `NOTIFY_CALLER` to that service account's email, and drop the separate `now-notify` SA from `setup-push.sh`. Still scripted: `roles/firebasecloudmessaging.admin` for the runtime SA, the FCM/installations APIs, the `push_sent.expires_at` TTL. The job's timezone now defaults to the machine's (`SCHEDULE_TZ` / `.now.env` override).
3. **Watch the first days of `now-app - health check failing`** (new uptime check). Done 2026-09-20: migration, monitoring apply, old alerts removed, widget switched to `https://now-app.web.app`, old service `now` deleted.
4. **Reconcile `.zilch.config` with reality** (see drift in [zilch-gcp](../architecture/zilch-gcp.md)) and decide whether `now` should adopt zilch's storage bucket or keep its own (recommended: keep; zilch's has `force_destroy = true`).
5. **Mention** `now` as a reference app in the zilch README (its commit `4d2eae8` is pushed).
6. **Git history still contains the old project id, number and Firebase web config** (early `web/auth.js`, docs, `.firebaserc`) and the owner's email (old `app/auth.py`). None are credentials (auth is enforced server-side and `ALLOWED_EMAIL`); rewriting public history needs a force push and breaks clones/forks, so it was left. Working tree scrubbed 2026-09-20.

**Loose ends found during the review**
- `db.init(memory=...)` parameter is vestigial. `requirements.txt` pins direct dependencies only (no lockfile).
- Every tree read after a write scans the whole `todos` collection (cached per revision); revisit past a few thousand todos.
- zilch `tfplan` file is an untracked leftover in `../zilch-gcp`.
