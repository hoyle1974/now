import importlib.util
import pathlib

import pytest

from app import blobstore, db
from tests.helpers import TEST_USER, wipe_users

spec = importlib.util.spec_from_file_location(
    "migrate", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "migrate-to-users.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture
def setup():
    db.init()
    wipe_users()
    client = db.get_conn()
    for name in migrate.COLLECTIONS:
        for d in client.collection(name).stream():
            d.reference.delete()
    yield client
    db.teardown()


def test_copies_collections_and_blobs_and_keeps_the_old_ones(setup):
    client = setup
    client.collection("todos").document("t1").set({"todo_id": "t1", "title": "old"})
    client.collection("meta").document("rev").set({"value": 7})
    client.collection("push_devices").document("d1").set({"token": "tok"})
    store = blobstore.use_memory()
    store.put("todos/t1/a1", b"img", "image/png")

    out = migrate.migrate(client, store, TEST_USER, dry_run=False)

    user = client.collection("users").document(TEST_USER)
    assert user.collection("todos").document("t1").get().to_dict()["title"] == "old"
    assert user.collection("meta").document("rev").get().to_dict() == {"value": 7}
    assert store.get(f"users/{TEST_USER}/todos/t1/a1") == (b"img", "image/png")
    assert client.collection("todos").document("t1").get().exists  # old data stays until you delete it
    assert store.get("todos/t1/a1") is not None
    assert out["docs"] == 3 and out["blobs"] == 1


def test_dry_run_writes_nothing(setup):
    client = setup
    client.collection("todos").document("t1").set({"todo_id": "t1"})
    out = migrate.migrate(client, blobstore.use_memory(), TEST_USER, dry_run=True)
    assert out["docs"] == 1
    assert not client.collection("users").document(TEST_USER).collection("todos").document("t1").get().exists


def test_only_missing_still_refreshes_meta_rev_but_skips_an_existing_todo(setup):
    client = setup
    client.collection("todos").document("t1").set({"todo_id": "t1", "title": "v1"})
    client.collection("meta").document("rev").set({"value": 1})
    store = blobstore.use_memory()
    migrate.migrate(client, store, TEST_USER, dry_run=False)

    # the old service bumps rev and edits t1 during the gap before the deploy finishes
    client.collection("meta").document("rev").set({"value": 99})
    dest = client.collection("users").document(TEST_USER)
    dest.collection("todos").document("t1").set({"todo_id": "t1", "title": "edited in new app"})

    migrate.migrate(client, store, TEST_USER, dry_run=False, only_missing=True)

    # meta/rev is always refreshed, even though it already existed at the destination
    assert dest.collection("meta").document("rev").get().to_dict() == {"value": 99}
    # an ordinary already-migrated document keeps the same only-missing skip behaviour
    assert dest.collection("todos").document("t1").get().to_dict()["title"] == "edited in new app"


class _SpyStore:
    """Wraps a MemoryStore and records whether get() was ever called."""

    def __init__(self, inner):
        self._inner = inner
        self.get_calls = 0

    def put(self, key, data, content_type):
        self._inner.put(key, data, content_type)

    def get(self, key):
        self.get_calls += 1
        return self._inner.get(key)

    def delete(self, key):
        self._inner.delete(key)

    def list_blobs(self, prefix):
        return self._inner.list_blobs(prefix)


def test_only_missing_checks_blob_existence_via_list_not_get(setup):
    client = setup
    inner = blobstore.use_memory()
    inner.put("todos/t1/a1", b"img", "image/png")
    migrate.migrate(client, inner, TEST_USER, dry_run=False)

    spy = _SpyStore(inner)
    out = migrate.migrate(client, spy, TEST_USER, dry_run=False, only_missing=True)

    assert out["blobs"] == 0
    assert spy.get_calls == 0  # existence was proven by list_blobs, not a per-blob download


def test_rerun_picks_up_writes_made_since_and_only_missing_keeps_new_edits(setup):
    client = setup
    store = blobstore.use_memory()
    client.collection("todos").document("t1").set({"todo_id": "t1", "title": "v1"})
    migrate.migrate(client, store, TEST_USER, dry_run=False)
    # the old service keeps writing until the deploy
    client.collection("todos").document("t2").set({"todo_id": "t2", "title": "late"})
    # ...and after the deploy the new code edits t1 in the new partition
    dest = client.collection("users").document(TEST_USER).collection("todos")
    dest.document("t1").set({"todo_id": "t1", "title": "edited in new app"})
    migrate.migrate(client, store, TEST_USER, dry_run=False, only_missing=True)
    assert dest.document("t2").get().to_dict()["title"] == "late"
    assert dest.document("t1").get().to_dict()["title"] == "edited in new app"
