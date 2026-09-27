---
type: Feature
title: Sharing between users
description: How an item and its subtree are shared read-only or read/write with every user of the deployment — share partitions, mounts, migration, routing, and what each role may do.
resource: app/shares.py
tags: [sharing, multi-user, data, sync]
timestamp: 2026-09-27T04:00:00Z
---
Design spec: `docs/superpowers/specs/2026-09-26-sharing-design.md`; plan: `docs/superpowers/plans/2026-09-26-sharing.md`. Everything is behind `SHARING_ENABLED` (off by default, `auth.sharing_enabled()`).

**Model.** Sharing an item moves it and its whole subtree out of the owner's partition into its own partition `shares/{id}` ([Firestore](../data/firestore.md)), where `id` is the root's todo id. No request ever reads another user's partition. Every member (the owner too) has a `mount` todo with the same id in their own partition ([item types](item-types.md)): it holds only where that person placed it. Audience is everyone on the deployment (`members: "all"`; a list of emails later). Mode is `ro` (strictly view-only) or `rw`. Only `shareable` types (`todo`, `list`, `project`, `note`) may be in a share: never a calendar, an event or a mount.

**Who may do what** is the fixture `tests/fixtures/share_rules.json` (owner / rw / ro / stranger / revoked × read, collapse, edit, check, add, delete, root delete, mode, unshare, move mount, drag across), checked against the routes by `tests/test_share_rules.py`.

**Migration** (`app/migrate.py`, `migrate_subtree(src, root_id, dst, kind=share|unshare|move)`). One routine moves a subtree between partitions for share, unshare and dragging an item into or out of a share. Ids, versions and every field are kept. Steps, recorded in the source's `meta/rev` under `migrating` with a 2-minute lease:
1. **frozen** — every other write to the source partition gets `db.Frozen` → 503 `migrating` (clients retry); the archive sweep skips it too.
2. **blobs** — attachment bytes copied to `{dst}/todos/...`.
3. **copied** — documents copied in batches of 200; the root is placed at its destination (share: top of the share; unshare: where the owner's mount was; move: `dst_parent`/`index`).
4. **switched** — source documents deleted (share: the root's own doc becomes the owner's mount, same place); destination siblings renumbered for a move; both revisions bumped; share state set (`active`, or `unshared` with `returned_to`); `shares_meta/rev` bumped for share/unshare.
5. **done** — source blobs deleted, freeze cleared.

Each step is safe to repeat. A run that dies leaves the freeze; when its lease has expired, `migrate.resume_if_stale(partition)` finishes it (called when a write hits the freeze, and on tree loads). Refusals (`MigrationError.detail`): `crosses share boundary` (a calendar item or mount would enter a share), `not eligible` (already shared, a mount, or not in a user's partition), `too large` (over 2,000 nodes), `parent not found`.

**Requests** on shared items carry `X-Share: <id>` ([routes](../api/routes.md)); `auth.bind_partition` checks membership and mode, then binds `shares/{id}`. A read-only member's `collapsed` patch goes to their own view state (`users/{email}/view_state/{id}`, 90-day TTL). Only the owner deletes or restores the root, and the root never moves inside the share (its place is each member's mount). Writes in a share stamp `last_edited_by`.
