---
type: Runbook
title: Multi-user (family) operations
description: Adding or removing a person from ALLOWED_EMAILS, migrating existing data into the per-user layout, and what stays owner-only.
resource: app/auth.py
tags: [multi-user, migration, auth, runbook]
timestamp: 2026-09-27T10:00:00Z
---
One deployment can serve a small family: each Google account in `ALLOWED_EMAILS` gets
its own fully isolated Firestore/storage partition ([data model](../data/firestore.md),
[stack](../architecture/stack.md)). An item can be shared with everyone on the deployment
([sharing](../features/sharing.md)); still no roles and no invite UI — the list is edited by
redeploying, not through the app. A person added later gets every existing share in their
list on their first load; a person removed loses access to shares at once (membership is
`ALLOWED_EMAILS`), and their own shares stay readable by the others until the owner's data
is dealt with by hand. See
[principles](../principles.md) for the cost note (reads scale with the number of
allowed users; fine at family scale, must be watched at anything bigger).

**Adding a person.** Redeploy with the fuller, `;`-separated list — the first entry is
always the owner (calendar feed and budget alerts stay theirs, see below):

```bash
ALLOWED_EMAILS='you@example.com;kid@example.com' ./deploy.sh
```

That's it for a brand-new account: `require_user` (`app/auth.py`) starts allowing the
new email immediately, and its first request creates its own empty `users/{email}/...`
partition on demand. Nothing needs to be migrated for someone who never had data before
this feature existed.

**Removing a person.** Redeploy with a shorter `ALLOWED_EMAILS` list. Their data is not
deleted automatically (nothing in this app deletes a user's partition on removal); do it
by hand with `gcloud firestore` / bucket tools if you want the data gone, or just leave
it — an unreachable partition costs nothing to sit idle.

**Migrating pre-existing (single-user) data — already done, historical.** Before this
feature, all data lived in top-level collections (`todos`, `todos_archive`, `txn_log`,
`meta`, `push_devices`, `push_sent`) and blobs under `todos/{id}/...`. That one-time
migration ran against production on 2026-09-21 (see `docs/okf/log.md`) and the old
top-level collections and blobs were deleted after verification — there is no old-format
data left to migrate, and the app has never had a second deployment that would need this
again. `scripts/migrate-to-users.py`, which did the copy, was deleted once the migration
was verified and logged; if this app is ever forked from a pre-multi-user commit and
needs the same one-time copy, recover it from git history (`git log --all --
scripts/migrate-to-users.py`) rather than writing it fresh.

**Owner-only surfaces.** The calendar feed and budget alerts both bind
`auth.owner()` (the first `ALLOWED_EMAILS` entry) regardless of who is signed in
elsewhere: the More panel shows no calendar link at all for a non-owner
([calendar feed](../features/calendar-feed.md), [ui-inventory](../features/ui-inventory.md)).
This is by design, not a bug to fix — there is one calendar subscription URL
and one budget per deployment, not one each.

**Out of scope: a device shared by two family members.** This plan does not address the
previous-person's-outbox / stale-push-token problem on a device more than one person
signs into. Each person is expected to use their own device. If two people do share a
device, expect stale pushes and an outbox mix-up — there is no guard against it.
