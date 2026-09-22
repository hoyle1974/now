---
type: Principles
title: Principles and non-goals
description: What this project is for (one deployment, a family, real daily use), the #1 rule (must cost nothing in GCP), and what it will never be.
tags: [principles, cost, multi-user, non-goals]
timestamp: 2026-09-22T00:15:00Z
---
**Status.** `now` began as a learning project. It is now a **real project the owner uses every day**. Treat it that way: data safety, reliability and a low maintenance burden matter more than novelty.

**One deployment, a family, by design.** Auth accepts a small, fixed list of Google accounts (`ALLOWED_EMAILS`, `;`-separated, first is the owner; legacy single-account `ALLOWED_EMAIL` still works, [stack](architecture/stack.md)). Each allowed email's data is fully isolated under its own Firestore/storage partition ([data model](data/firestore.md)) — but there is still no sharing between people, no roles, no invite UI, and none will be added; the list is edited by redeploying with a new `ALLOWED_EMAILS` value, not through the app. Anyone else who wants to use it clones the repo, creates **their own GCP project**, deploys it and runs it themselves ([forking](ops/forking.md)). Fork-friendliness means "easy for one household to run their own copy", never "a multi-tenant SaaS serving strangers". A device shared by two people in the same household is out of scope — each person is expected to use their own device ([multi-user runbook](ops/multi-user.md)).

**Cost note: reads scale with the number of allowed users.** Every allowed email is looped over on every notify/digest pass ([push reminders](features/push-reminders.md)) and, per the sync/tree-read model, costs roughly one Firestore tree read per user per rev change. This is negligible and acceptable at family scale (a handful of people), but it is a multiplier on the read count the cost guards below watch — it is not free just because the app is.

**No rollback.** Rollback is not a feature. The owner always runs the latest deploy, so only the newest container image is kept (Artifact Registry cleanup policy, [deploy](ops/deploy.md)). To go back, redeploy an older commit.

**The #1 rule: it must not cost anything in GCP for the owner's usage.** It has to stay inside the free tier (request-based Cloud Run billing, max instances 1, Firestore within free quotas, no always-on resources). Every design decision is checked against this first; a feature that cannot be done for free does not ship (or ships off by default).

**If cost could break, be VERY VERY VERY loud.** Any change, finding or observation suggesting spend could leave free-tier territory (always-on CPU, min instances, scanning reads that scale with data, a chatty scheduler, a new billed API, storage growth) must be stated prominently and immediately, in the reply, the commit message, and here, not buried in a log line. Guards, in order of how early they fire:
1. **`scripts/cost-check.sh`** (read-only, prints a loud banner and exits 1): Cloud Run CPU throttling, min 0 / max 1 instances, real Artifact Registry image size vs 512 MB, no VMs / reserved IPs / Cloud SQL, at most 3 Scheduler jobs, buckets in free-tier regions, a budget exists, Firestore reads/writes/deletes in the last 24 h vs the free quota (warns at 50%). **`deploy.sh` runs it after every deploy** and `doctor.sh` includes it.
2. A $1 monthly budget alert with thresholds at 1% / 50% / 100% (`scripts/setup-cost-guards.sh`), emailed to billing admins **and pushed to your phone at any hour** ([push reminders](features/push-reminders.md)). Budget alerts lag by hours to a day and only email the billing admins; they are a backstop, not the first line.

Other guards: `--cpu-throttling` and max instances 1 ([deploy](ops/deploy.md)), the read guard in [push reminders](features/push-reminders.md), `scripts/setup-cost-guards.sh`, and `scripts/doctor.sh` (fails on always-on CPU). History: an always-on CPU misconfiguration billed about $30/month before it was caught ([log](log.md), 2026-09-21).
