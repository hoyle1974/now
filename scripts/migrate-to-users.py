#!/usr/bin/env python3
"""One-off: copy the pre-multi-user data (top-level todos, todos_archive, txn_log, meta,
push_devices, push_sent, and blobs under todos/) into users/{OWNER}/…. Dry run unless
--apply. Copies only: the old data is left in place so you can roll back; delete it by
hand after you have verified the app (see docs/okf/ops/multi-user.md). Safe to re-run
(overwrites from the old data); after the deploy use --only-missing so nothing edited
through the new code is overwritten.

Run against production with real credentials:
  GOOGLE_CLOUD_PROJECT=<project> ATTACHMENTS_BUCKET=<bucket> python scripts/migrate-to-users.py you@example.com --apply
Take a backup first: gcloud firestore export gs://<bucket>/backup-$(date +%F)
"""
from __future__ import annotations

import sys

COLLECTIONS = ("todos", "todos_archive", "txn_log", "meta", "push_devices", "push_sent")
BATCH = 400  # Firestore allows 500 writes per batch


def migrate(client, store, owner: str, dry_run: bool, only_missing: bool = False) -> dict:
    owner = owner.strip().lower()
    dest = client.collection("users").document(owner)
    docs = blobs = 0
    for name in COLLECTIONS:
        batch, pending = client.batch(), 0
        for snap in client.collection(name).stream():
            # meta/rev is the revision counter, not user data: a stale copy could let a
            # client believe an old rev is current, so it's always refreshed even under
            # --only-missing, unlike every other (idempotency-preferring) document here.
            always_copy = name == "meta" and snap.id == "rev"
            if only_missing and not always_copy and dest.collection(name).document(snap.id).get().exists:
                continue
            docs += 1
            if dry_run:
                continue
            batch.set(dest.collection(name).document(snap.id), snap.to_dict())
            pending += 1
            if pending == BATCH:
                batch.commit()
                batch, pending = client.batch(), 0
        if pending:
            batch.commit()
    # Under --only-missing, check existence via one listing call rather than a per-blob
    # get() (which does a full download): re-downloading every already-migrated image
    # on each catch-up run would be real, avoidable GCS cost.
    existing = ({key for key, _created in store.list_blobs(f"users/{owner}/todos/")}
                if only_missing else set())
    for key, _created in store.list_blobs("todos/"):
        dest_key = f"users/{owner}/{key}"
        if only_missing and dest_key in existing:
            continue
        blobs += 1
        if dry_run:
            continue
        got = store.get(key)
        if got is None:
            # The blob was deleted concurrently between the list above and this copy;
            # nothing to migrate for it.
            continue
        data, content_type = got
        store.put(dest_key, data, content_type)
    return {"docs": docs, "blobs": blobs, "dry_run": dry_run}


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    from google.cloud import firestore

    from app import blobstore
    result = migrate(firestore.Client(), blobstore.get_store(), argv[0], dry_run="--apply" not in argv,
                     only_missing="--only-missing" in argv)
    print(result, "(dry run: nothing written; pass --apply)" if result["dry_run"] else "(copied)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
