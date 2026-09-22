---
type: Runbook
title: Multi-user (family) operations
description: Adding or removing a person from ALLOWED_EMAILS, migrating existing data into the per-user layout, and what stays owner-only.
resource: app/auth.py
tags: [multi-user, migration, auth, runbook]
timestamp: 2026-09-22T00:15:00Z
---
One deployment can serve a small family: each Google account in `ALLOWED_EMAILS` gets
its own fully isolated Firestore/storage partition ([data model](../data/firestore.md),
[stack](../architecture/stack.md)). There is still no sharing between them, no roles, no
invite UI — the list is edited by redeploying, not through the app. See
[principles](../principles.md) for the cost note (reads scale with the number of
allowed users; fine at family scale, must be watched at anything bigger).

**Adding a person.** Redeploy with the fuller, `;`-separated list — the first entry is
always the owner (widget, calendar feed and budget alerts stay theirs, see below):

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

**Migrating pre-existing (single-user) data.** Before this feature, all data lived in
top-level collections (`todos`, `todos_archive`, `txn_log`, `meta`, `push_devices`,
`push_sent`) and blobs under `todos/{id}/...`. `scripts/migrate-to-users.py` copies that
into the owner's partition (`users/{OWNER}/...`). Order matters, because the *old*
service keeps writing to the old collections until the new deploy is live:

1. **Backup first:** `gcloud firestore export gs://<bucket>/backups/<date>`.
2. **Dry run:** `python scripts/migrate-to-users.py OWNER` (prints what it would copy,
   changes nothing).
3. **Apply, then deploy immediately:** `python scripts/migrate-to-users.py OWNER --apply`
   followed right away by `ALLOWED_EMAILS='owner;kid' ./deploy.sh` — minimize the gap
   where the old service can still write to the old (now stale) collections.
4. **Catch up the gap:** `python scripts/migrate-to-users.py OWNER --apply --only-missing`
   right after the deploy finishes, to copy anything the old service wrote during the
   gap. `--only-missing` never overwrites anything the new code has since edited.
5. **Verify as the owner:** old todos and images are present and correct.
6. **Only then clean up:** delete the old top-level collections and the old
   `todos/{id}/...` blobs by hand (not automated — this is a one-way, destructive step).

**Owner-only surfaces.** The widget token, the calendar feed and budget alerts all bind
`auth.owner()` (the first `ALLOWED_EMAILS` entry) regardless of who is signed in
elsewhere: the More panel shows no calendar link at all for a non-owner
([calendar feed](../features/calendar-feed.md), [ui-inventory](../features/ui-inventory.md)).
This is by design, not a bug to fix — there is one widget, one calendar subscription URL
and one budget per deployment, not one each.

**Out of scope: a device shared by two family members.** This plan does not address the
previous-person's-outbox / stale-push-token problem on a device more than one person
signs into. Each person is expected to use their own device. If two people do share a
device, expect stale pushes and an outbox mix-up — there is no guard against it.
