# Sharing between users on one deployment — design

Date: 2026-09-26. Status: approved in brainstorming, awaiting spec review.

## Goal

Let the owner of an item share it, with its whole subtree, with the other users of the
same deployment (`ALLOWED_EMAILS`, typically 1–8 people), either **read-only** or
**read/write**. Every member sees the shared item in their own list, placed wherever they
like, badged as shared, and kept live as anyone with edit rights changes it.

This reverses the "no sharing, ever" line in `docs/okf/principles.md` for users of the
same deployment only.

### Out of scope

- **Public (unauthenticated) links.** Considered and dropped: a no-login route that reads
  Firestore is a cost and abuse risk. Still a non-goal.
- **Choosing members per share.** v1 shares with everyone. The data model has a `members`
  field (`"all"` now, a list of emails later) so this needs no migration.
- **Assignees**, a "can check off" mode between read-only and read/write, and per-share
  reminder opt-outs. Each can be added later without changing the data model
  (`mode` is a string).
- Sharing `calendar` / `calendar_event` items. The app is not the source of truth for them.

## Decisions (from brainstorming)

| # | Decision |
|---|---|
| D1 | A shared subtree **moves out of the owner's partition** into its own partition `shares/{share_id}`. No request ever reads another user's partition. |
| D2 | `share_id` equals the shared root's todo id. Each member (the owner included) has a **mount** doc with that same id in their own partition, which holds only position. |
| D3 | Members see the mount at their root at first and may move it anywhere in their own tree. Placement is per person. |
| D4 | Audience is "everyone on the deployment". Mode is `ro` or `rw`. |
| D5 | Read-only is **strictly view-only**: no checking off, no edits. Collapse/expand, moving your mount and removing your mount still work. |
| D6 | Only `todo`, `list`, `project`, `note` roots can be shared, and only when the subtree has no `calendar`/`calendar_event` items. |
| D7 | Per-viewer view state (`collapsed`) for shared nodes lives in `users/{viewer}/view_state/{share_id}` with a 90-day TTL. |
| D8 | Moving an existing item across a share's edge (in or out) is allowed and runs the same subtree migration as sharing, after a confirm. Needs `rw` (or owner). |
| D9 | `blocked_by` and `references` may only point at ids in the same partition. |
| D10 | Edits addressed to an item's old home (after a share/unshare/cross-edge move) are resolved to its new home by the server and applied. Only a recipient whose access was revoked loses queued edits, with a visible notice. |
| D11 | Shared items appear in **every member's** Next up, digest and heads-ups (members whose mount is not removed). Push dedup stays per user. |
| D12 | Only the owner can change mode, unshare, or delete the shared root. `rw` members can edit, add and delete anything inside it. |
| D13 | Unshare: the subtree moves back to the owner; other members' mounts disappear and the mascot says so. No stub, no copy. |
| D14 | Owner deletes the shared root: it goes to the share's trash, members' mounts hide; restore brings them back; the archive sweep eventually ends the share. |
| D15 | New share mounts are announced by the mascot. Remote-change bubbles name the editor ("Alex checked off 'Book hotel'"). |
| D16 | The ICS calendar feed stays the owner's private items only. |
| D17 | Share and unshare are online-only actions (spinner, then tree reload). |
| D18 | Everything ships behind `SHARING_ENABLED` (off by default), in phases, after a manual Firestore + attachments backup. |

## Data model

### Partitions

`app/tenant.py` today binds the signed-in user's email and every Firestore path and blob
key is derived from it (`db_firestore.user_ref`, `blobstore.user_todos_prefix`). It will
bind two things:

- **user**: the signed-in email (identity; used for permissions, push devices, mounts,
  view state, calendar feed).
- **partition**: `users/{email}` by default, or `shares/{share_id}` for a share-bound
  request.

`user_ref()` becomes `partition_ref()` and the blob prefix becomes `{partition}/todos/`.
All existing db functions (including `txn_log`, which is per partition) then run
unchanged inside a share. Code that needs the person (push devices, mounts, view state,
calendar feed) asks for the user explicitly.

### `shares/{share_id}` (new)

```
owner:        email
members:      "all"                          # later: [email, ...]
mode:         "ro" | "rw"
state:        "active" | "migrating" | "unshared"
returned_to:  email | null                   # set when unshared; tombstone kept 30 days
created_at, updated_at
```

Subcollections, same as a user partition: `todos`, `todos_archive`, `txn_log`,
`meta/rev`, `meta/archive`. Blobs under `shares/{share_id}/todos/...`.

A global `shares_meta/rev` doc is bumped on share, unshare and mode change so clients
notice a changed share list.

### `mount` item type (new)

Added to `app/types.json`. Lives only in user partitions, at `users/{u}/todos/{share_id}`.
Fields: `parent_id`, `order_idx`, `deleted` (soft delete = "removed from my list"),
`share_id`. No content fields. Never appears in a share partition. A removed mount is
not listed in Trash and is never archived by the sweep; it comes back through
"Shared with me" (or the undo toast).

### `users/{u}/view_state/{share_id}` (new)

```
collapsed:  [node ids]
expires_at: now + 90 days, refreshed on every write   # Firestore TTL (collection group)
```

Expiry only means shared nodes show expanded again.

### Todo changes

- `last_edited_by` (email): set server-side on every write inside a share partition.
- `blocked_by`, `references`: validated to be in the same partition (D9).
- `collapsed` on a shared node is never written to the share; it is routed to view state.
- Derived on `GET /todos/tree`, never stored: `share: {id, mode, owner}` on every node from
  a share, and `share_root: true` on the root.

### Invariants (server-enforced)

- No `mount` inside a share partition.
- No `calendar` / `calendar_event` inside a share partition.
- A share root is never inside another share.
- A share partition has exactly one root, whose id equals `share_id`.
- A share has at most 2,000 nodes (the migration size cap).

## Server

### Routing and permissions

A dependency `bind_partition` runs after `bind_user`:

- No `X-Share` header → partition `users/{user}` (today's behaviour).
- `X-Share: X` → load `shares/X`; require: state not `unshared` (except the old-home
  rule below), user is a member, for writes `mode == rw` or user is owner, owner-only
  actions (share/mode routes, deleting the root) only by the owner. Then bind
  `shares/X`.

New refusals, told apart by `detail`:

| Status | `detail` | Client does |
|---|---|---|
| 403 | `share revoked`, `read only`, `owner only` | Drop the op, show a notice |
| 409 | `crosses share boundary` | Drop the op, reload (an invariant failed) |
| 503 | `migrating` | Retry with backoff (existing 5xx path) |

A 403 without these details keeps today's sign-in retry behaviour.

**Mount and root share an id.** Reparent / move of node X *without* `X-Share` act on the
caller's mount doc. Content ops *with* `X-Share` act on the share root. A
`collapsed`-only patch with `X-Share` is written to the caller's view state instead
(the client op is unchanged). A mount may only be reparented under the caller's own items
or root, never under a shared node.

**Old-home resolution (D10).** When a handler cannot find the addressed todo:

1. The idempotency check in the addressed partition's `txn_log` runs first (already true
   in `run_atomic`; verify and cover with a test). An op committed before a migration
   returns its stored outcome.
2. `locate(id)` tries: the caller's partition, each share the caller has mounted, and
   unshared tombstones with `returned_to == caller`.
3. If found: rebind, re-check permissions, run. The response carries `X-Partition`.
   If found but the caller may not write there: the matching 403.

**Cross-edge reparent (D8).** `PATCH /todos/{id}/reparent` gains `parent_share`
(`null` = caller's partition). If the item's partition differs from the target's, the
reparent is a `migrate_subtree`.

### `migrate_subtree(src, root_id, dst, dst_parent, index)`

Used for share, unshare, drag in and drag out.

1. **Validate**: permissions, invariants, size cap.
2. **Freeze**: write `migrating: {root_id, ids, step, lease_until}` into the source's
   `meta/rev` doc (already read by every write transaction, so no extra read). Writes to
   frozen ids return 503 `migrating`. When sharing, first create the share doc with
   `state: migrating`.
3. **Copy blobs** to the destination prefix (idempotent).
4. **Copy docs** in batches of ≤200 writes, preserving ids, versions and every field;
   only the root's `parent_id` / `order_idx` change.
5. **Switch**: delete source docs in batches; when sharing, overwrite the root's doc in
   the owner's partition with the `mount` doc (same id, same position); when unsharing,
   write the root back in place of the owner's mount and delete other members' mounts
   lazily (they are skipped by the tree read once the share is `unshared`, and removed
   by the sweep). Bump both partitions' revs and `shares_meta/rev`, set share state,
   clear the freeze.
6. **Delete source blobs.**

Runs inline in the request. The `step` is recorded after each stage; if the request dies,
the lease expires and the next tree load of either partition resumes from `step`. Every
step is safe to repeat because ids are preserved.

### Reads

- **`GET /todos/tree`**: the caller's tree (cached per partition rev), plus for each
  mount that is not removed: the share tree (cached per share rev), spliced under the
  mount's position, tagged with `share`, with `collapsed` overlaid from view state. A
  mount whose share is `unshared` or whose root is deleted is left out. Missing mounts
  for active shares the caller is a member of are created at the caller's root
  (covers new users) and reported so the client can announce them.
- **Revs**: `/todos/rev` and the tree return `rev` (the caller's own partition, integer,
  kept for old clients) and `revs: {"users/<u>": n, "shares/<id>": n, ..., "shares": n}`
  (`"shares"` = `shares_meta/rev`). Cost: 2 + number of mounted shares gets.
- **`GET /todos/next`**: ranks the caller's tree merged with their mounted share trees.
- **`GET /todos/trash`**: the caller's trash plus the trash of every share where the
  caller can edit, each entry labelled with its share.

### Background work

- **Notify** (`/internal/notify`): for each user, also read that user's mounted, non-removed
  shares. `push_sent` stays per user.
- **Heads-up tasks**: a task for a shared item carries the `partition`; the handler fans out
  to every member with a non-removed mount.
- **Archive sweep, `txn_log` prune**: loop over shares as well as users. Unshared
  tombstones (and their `txn_log`) are deleted after 30 days. A share whose root was
  archived ends: share doc, mounts and view state are cleaned up.
- **Calendar feed**: unchanged; owner's private partition only.

### New routes

| Route | Purpose |
|---|---|
| `PUT /todos/{id}/share` `{mode}` | Owner: share a root (migration) or change mode. 400 if not eligible (type, calendar inside, already in a share). |
| `DELETE /todos/{id}/share` | Owner: unshare (migration back). |
| `GET /shares` | "Shared with me": every active share the caller can see, with owner, mode, title, and whether the caller's mount is removed. |

Re-adding a removed mount uses the existing `PATCH /todos/{id}/undelete` on the mount.
All share routes return 404 while `SHARING_ENABLED` is off, and no mounts are created.

## Client

- **Model**: the server returns mount+root merged, so the client sees one node with
  `share` and `share_root`. Tree code does not know about mounts.
- **Routing** (`web/sync.js`): at enqueue an op takes its target's `share.id`; the request
  sends `X-Share`. Exception: reparent / move of a `share_root` node sends no header (it
  moves the mount). A response `X-Partition` re-points queued ops for that id. Routing is
  one step in the request builder, not per-op code.
- **Revs**: `knownRev` becomes a map keyed by partition. Write responses report
  `X-Rev-Prev` / `X-Rev` for the partition they hit (plus `X-Partition`). Stale when any
  component rose or the key set changed.
- **Refusals**: `share revoked` / `read only` / `owner only` drop the op with a notice
  ("3 edits to 'Portland trip' couldn't be saved — it's no longer shared with you").
- **Read-only locking** (`render-node.js`, `fields-ui.js`, `reorder.js`): inside an `ro`
  share, checkbox, inline edit, field sheet edits, add-child and drag are disabled;
  collapse/expand and moving the root (the mount) still work.
- **Badges**: small shared icon on every shared node; the root shows a chip
  "Shared · can edit" / "Shared · read-only" plus "· <name>" when it isn't yours. Same chip
  in Next up.
- **Sharing row** in the field sheet: Private / Everyone can view / Everyone can edit.
  Owner only, eligible roots only. Online-only with a "Sharing…" spinner, then a tree
  reload. Offline: "Go online to change sharing". Unshare confirms: "Stop sharing? It
  disappears for everyone else."
- **Cross-edge drag**: confirm ("Everyone will see 'Buy cake'" / "This removes 'Milk' for
  everyone"), then an outbox reparent with `parent_share` and reload-after-ack.
- **Mounts**: Delete on a `share_root` reads "Remove from my list" (undo toast works).
  More panel gains **Shared with me** (`GET /shares`): Add to my list / Remove.
- **Trash**: shared entries labelled "from <title> (shared)"; restore routes to the share.
- **Mascot**: new mounts ("Sam shared 'Portland trip' with everyone"), unshare and owner
  delete ("Sam stopped sharing 'Portland trip'"), and `remote-diff.js` names the editor
  from `last_edited_by`. A person's name is the email's local part for now.
- **Search** covers shared items with no change (client-side over the merged tree).

## Vignettes (expected behaviour)

Cast: **you** (owner), **Alex** and **Robin** (other users).

1. **Share.** You set "Portland trip" to Everyone can edit. It keeps its place in your list
   with a "Shared · can edit" chip. Alex's next refresh shows it at Alex's root with
   "Shared · can edit · you", and the mascot announces it.
2. **Alex deletes a child.** "Book hotel" disappears for everyone; your mascot says Alex
   deleted it. Alex's undo toast works. It sits in the share's trash, visible to you and
   Alex (both can edit).
3. **A due date.** "Pay the plumber", due Friday 9:00, shows in Next up and the digest for
   you, Alex and Robin, each deduplicated separately.
4. **Unshared while Alex is offline.** Alex's three queued edits are refused with
   `share revoked` and dropped; Alex sees a notice. The mount is gone; the mascot explains.
5. **Robin, read-only.** Robin sees "Chores" with "Shared · read-only". No checkbox, no
   edits. Robin can collapse nodes and move the mount anywhere.
6. **Alex removes the mount and wants it back.** "Remove from my list" hides it (and its
   reminders). Later, More → Shared with me → Add to my list brings it back at root.
7. **You rename it and move it under "2026".** Alex sees the new title; Alex's placement is
   unchanged. If you delete it, members' mounts hide; restoring brings them back.
8. **Your phone was offline when your laptop shared it.** The phone's queued edits to
   "Book hotel" are resolved to the share and applied; nothing is lost.
9. **Alex drags "Buy cake" into Groceries.** Confirm: "Everyone will see 'Buy cake'". It
   migrates into the share. Dragging "Milk" out confirms "This removes 'Milk' for
   everyone" and migrates it to Alex's partition.

## Rollout

0. **Backup**: `gcloud firestore export` to a GCS bucket and a copy of the attachments
   bucket, kept until phase 4 is verified (scheduled backups and PITR expire after 7
   days). Repeat just before the phase 3 deploy.
1. **Partition refactor**, no behaviour change. All existing tests green, especially
   `test_tenant_isolation`.
2. **Revs map**, backward compatible (`rev` kept). Client moves to the map. Bump
   `APP_VERSION`.
3. **Server sharing** behind `SHARING_ENABLED` (off): share docs, migration, routing,
   permissions, old-home resolution, splice, view state, Next up, notify, sweeps, routes.
4. **Client UI**, then turn `SHARING_ENABLED` on in production.

The flag is also a kill switch: off hides share routes and stops creating mounts;
existing share data is untouched.

## Testing

- **Python (emulator)**
  - Permissions matrix, table-driven: owner / rw member / ro member / non-member /
    removed mount / unshared tombstone × every route. Nobody reads another user's
    partition.
  - `migrate_subtree`: share, unshare, drag in, drag out; ids, versions and fields
    preserved; blobs moved; invariants refused (calendar, mount, nesting, size cap);
    >200 docs; a crash injected at every step, then resumed; frozen writes get 503.
  - Old-home resolution: each case (owner's other device on share, any device in the gap,
    owner on unshare, revoked recipient), including a pre-migration committed op replayed
    after the migration (stored outcome, not applied twice).
  - Reads: splice, auto-mount for a new user, view-state overlay and TTL field, revs map,
    Next up merge, trash across shares.
  - Background: notify fan-out with per-user dedup, heads-up task fan-out, archive/prune
    over shares, tombstone expiry, share end on archive.
- **Shared fixture** `tests/fixtures/share_rules.json`: what each role may do, checked by
  the server tests and by the client's read-only locking tests (same pattern as
  `tree_rules.json`).
- **JS** (`node --test`): `X-Share` routing incl. the mount exception, `X-Partition`
  re-pointing, new refusals, revs-map staleness, `remote-diff` names.
- **e2e**: two users against the emulator: share → other edits → owner sees it → mode to ro
  → edit refused → unshare. `tests_js/e2e_server.py` gains a way to pick the acting user.
- **Chrome**: two signed-in sessions (second Chrome profile) locally; sharing steps added
  to `docs/okf/ops/local-browser-testing.md`.

## Cost

Reads rise by about one share-tree read per mounted share per rev change, one per share
per notify pass, and 2 + N gets per `/todos/rev`. Migrations are rare, bounded by the
2,000-node cap. No always-on resources, no new scheduler jobs, no new billed APIs. Backup
storage is a few MB. At 1–8 users this stays well inside the free tier.

## Docs (OKF) to update with the implementation

Rewrite `principles.md` (sharing within one deployment; still no public links or
strangers), `ops/multi-user.md`, `architecture/client-server-split.md` (permissions,
migration, splice, Next up merge server-side; locking and badges client-side). Update
`data/firestore.md`, `data/todo.md`, `api/routes.md`, `features/sync-model.md`,
`features/item-types.md`, `features/next-up.md`, `features/push-reminders.md`,
`features/trash-archive.md`, `features/ui-inventory.md`, `ops/testing.md`,
`ops/local-browser-testing.md`, `ops/monitoring-backups.md` (the pre-rollout export).
New `features/sharing.md`. A `log.md` line per phase.
