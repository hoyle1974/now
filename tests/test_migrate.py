"""Moving a subtree between partitions (app/migrate.py): share, unshare, drag in/out."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app import blobstore, db, migrate, models, shares, tenant
from app.main import app
from tests.helpers import OTHER_USER, TEST_USER, act_as, wipe_users

ME = f"users/{TEST_USER}"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("SHARING_ENABLED", "1")
    db.init()
    wipe_users()
    blobstore.use_memory()
    with tenant.as_user(TEST_USER):
        yield
    app.dependency_overrides.clear()
    db.teardown()


def mk(title, parent=None, type="todo", order=0, deleted=False, attachment=None, partition=None) -> str:
    t = models.Todo(title=title, type=type, order_idx=order, deleted=deleted,
                    parent_id=None if parent is None else models.TodoId(parent))
    if attachment:
        t.attachments = [models.Attachment(id=attachment, name="a.png", content_type="image/png", size=3)]
    part = partition or tenant.partition()
    with tenant.as_partition(part):
        db.run_atomic(None, lambda: (db.create_todo(t), (200, None))[-1])
        if attachment:
            blobstore.get_store().put(blobstore.key_for(str(t.todo_id), attachment), b"png", "image/png")
    return str(t.todo_id)


def docs(partition) -> dict[str, dict]:
    return {d.id: d.to_dict() for d in db.partition_ref(partition).collection("todos").stream()}


def rev_doc(partition) -> dict:
    snap = db.partition_ref(partition).collection("meta").document("rev").get()
    return snap.to_dict() if snap.exists else {}


def trip() -> dict:
    """A (root, order 0), then R (list, order 1) holding C1 (with an image, holding G),
    C2 and a deleted D."""
    ids = {"A": mk("A", order=0), "R": mk("Trip", type="list", order=1)}
    ids["C1"] = mk("C1", ids["R"], order=0, attachment="img1")
    ids["G"] = mk("G", ids["C1"], order=0)
    ids["C2"] = mk("C2", ids["R"], order=1)
    ids["D"] = mk("D", ids["R"], order=2, deleted=True)
    return ids


def assert_shared(ids):
    R = ids["R"]
    shared = docs(f"shares/{R}")
    assert set(shared) == {ids[k] for k in ("R", "C1", "G", "C2", "D")}
    assert shared[R]["parent_id"] is None and shared[R]["type"] == "list"
    assert shared[ids["G"]]["parent_id"] == ids["C1"]
    mine = docs(ME)
    assert set(mine) == {ids["A"], R}
    assert mine[R]["type"] == "mount" and mine[R]["parent_id"] is None and mine[R]["order_idx"] == 1
    store = blobstore.get_store()
    assert store.get(f"shares/{R}/todos/{ids['C1']}/img1") is not None
    assert store.get(f"{ME}/todos/{ids['C1']}/img1") is None
    share = shares.get(R)
    assert share.state == "active" and share.owner == TEST_USER and share.mode == "rw"
    assert "migrating" not in rev_doc(ME)


def test_share_moves_subtree_and_leaves_mount():
    ids = trip()
    versions = {k: d["version"] for k, d in docs(ME).items()}
    meta = shares.meta_rev()
    rev_before = db.get_rev()
    migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw")
    assert_shared(ids)
    shared = docs(f"shares/{ids['R']}")
    assert all(shared[k]["version"] == versions[k] for k in shared)
    assert shares.meta_rev() == meta + 1
    assert db.get_rev() > rev_before
    with tenant.as_partition(f"shares/{ids['R']}"):
        assert db.get_rev() >= 1


def test_unshare_returns_subtree_to_mount_position():
    ids = trip()
    R = ids["R"]
    migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="rw")
    db.partition_ref(ME).collection("todos").document(R).update({"parent_id": ids["A"], "order_idx": 0})
    migrate.migrate_subtree(f"shares/{R}", R, ME, kind="unshare")
    mine = docs(ME)
    assert mine[R]["type"] == "list" and mine[R]["parent_id"] == ids["A"] and mine[R]["order_idx"] == 0
    assert {ids[k] for k in ("C1", "G", "C2", "D")} <= set(mine)
    assert docs(f"shares/{R}") == {}
    share = shares.get(R)
    assert share.state == "unshared" and share.returned_to == TEST_USER
    assert blobstore.get_store().get(f"{ME}/todos/{ids['C1']}/img1") is not None


def test_move_into_share_renumbers_siblings():
    ids = trip()
    R = ids["R"]
    migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="rw")
    P = mk("Buy cake", order=2)
    P1 = mk("candles", P)
    migrate.migrate_subtree(ME, P, f"shares/{R}", dst_parent=R, index=0, kind="move")
    shared = docs(f"shares/{R}")
    assert shared[P]["parent_id"] == R and shared[P]["order_idx"] == 0
    assert shared[P1]["parent_id"] == P
    assert shared[ids["C1"]]["order_idx"] == 1 and shared[ids["C2"]]["order_idx"] == 2
    assert P not in docs(ME) and P1 not in docs(ME)


def test_move_out_of_share_lands_in_the_movers_partition():
    ids = trip()
    R = ids["R"]
    migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="rw")
    other = f"users/{OTHER_USER}"
    existing = mk("theirs", partition=other)
    with tenant.as_user(OTHER_USER):
        migrate.migrate_subtree(f"shares/{R}", ids["C2"], other, dst_parent=None, index=0, kind="move")
    theirs = docs(other)
    assert theirs[ids["C2"]]["parent_id"] is None and theirs[ids["C2"]]["order_idx"] == 0
    assert theirs[existing]["order_idx"] == 1
    assert ids["C2"] not in docs(f"shares/{R}")


def test_refuses_calendar_inside():
    R = mk("Trip", type="list")
    mk("Cal", R, type="calendar")
    with pytest.raises(migrate.MigrationError) as e:
        migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="rw")
    assert e.value.detail == "crosses share boundary"
    assert docs(f"shares/{R}") == {} and shares.get(R) is None


def test_refuses_mount_inside():
    R = mk("Trip", type="list")
    mk("", R, type="mount")
    with pytest.raises(migrate.MigrationError) as e:
        migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="rw")
    assert e.value.detail == "crosses share boundary"


def test_refuses_sharing_a_mount_or_from_a_share():
    ids = trip()
    R = ids["R"]
    migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="rw")
    with pytest.raises(migrate.MigrationError) as e:
        migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="rw")
    assert e.value.detail == "not eligible"
    with pytest.raises(migrate.MigrationError) as e:
        migrate.migrate_subtree(f"shares/{R}", ids["C1"], f"shares/{ids['C1']}", kind="share", mode="rw")
    assert e.value.detail == "not eligible"


def test_refuses_over_size_cap(monkeypatch):
    monkeypatch.setattr(migrate, "MAX_NODES", 3)
    ids = trip()
    with pytest.raises(migrate.MigrationError) as e:
        migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw")
    assert e.value.detail == "too large"


def test_over_200_docs_are_batched():
    R = mk("Big", type="list")
    batch = db.get_conn().batch()
    for i in range(250):
        t = models.Todo(title=f"t{i}", parent_id=models.TodoId(R), order_idx=i)
        from app.db_firestore_helpers import todo_to_doc
        batch.set(db.partition_ref(ME).collection("todos").document(str(t.todo_id)), todo_to_doc(t))
        if i % 200 == 199:
            batch.commit()
            batch = db.get_conn().batch()
    batch.commit()
    migrate.migrate_subtree(ME, R, f"shares/{R}", kind="share", mode="ro")
    assert len(docs(f"shares/{R}")) == 251
    assert set(docs(ME)) == {R}


@pytest.mark.parametrize("step", ["frozen", "blobs", "copied", "switched"])
def test_crash_then_resume_every_step(step):
    ids = trip()
    with pytest.raises(RuntimeError, match="injected"):
        migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw", crash_after=step)
    assert "migrating" in rev_doc(ME)
    assert migrate.resume_if_stale(ME) is False, "a live lease is left alone"
    past = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)).isoformat()
    db.partition_ref(ME).collection("meta").document("rev").update({"migrating.lease_until": past})
    assert migrate.resume_if_stale(ME) is True
    assert_shared(ids)


def test_write_during_freeze_is_503():
    ids = trip()
    with pytest.raises(RuntimeError):
        migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw", crash_after="frozen")
    with pytest.raises(db.Frozen):
        db.run_atomic(None, lambda: (db.create_todo(models.Todo(title="x")), (200, None))[-1])
    act_as(app, TEST_USER)
    r = TestClient(app).patch(f"/todos/{ids['A']}", json={"title": "y"})
    assert r.status_code == 503 and r.json()["detail"] == "migrating"
    with pytest.raises(db.Frozen):
        migrate.migrate_subtree(ME, ids["A"], f"shares/{ids['A']}", kind="share", mode="rw")


def test_archive_sweep_leaves_a_frozen_partition_alone():
    ids = trip()
    old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)).isoformat()
    db.partition_ref(ME).collection("todos").document(ids["D"]).update({"deleted_at": old})
    with pytest.raises(RuntimeError):
        migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw", crash_after="blobs")
    with pytest.raises(db.Frozen):
        db.archive_expired()
    assert ids["D"] in docs(ME)


# ---- ultra review fixes ------------------------------------------------------------

def test_items_added_between_snapshot_and_freeze_move_too(monkeypatch):
    ids = trip()
    real = migrate._freeze
    added = {}

    def late_child_then_freeze(src, record):
        added["id"] = mk("late", ids["C2"], attachment="img2")  # lands before the lock
        return real(src, record)
    monkeypatch.setattr(migrate, "_freeze", late_child_then_freeze)
    migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw")
    assert added["id"] in docs(f"shares/{ids['R']}")
    assert added["id"] not in docs(ME)
    assert blobstore.get_store().get(f"shares/{ids['R']}/todos/{added['id']}/img2") is not None


def test_move_to_the_top_of_a_share_is_refused():
    ids = trip()
    migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw")
    P = mk("stray")
    with pytest.raises(migrate.MigrationError) as e:
        migrate.migrate_subtree(ME, P, f"shares/{ids['R']}", dst_parent=None, index=0, kind="move")
    assert e.value.detail == "crosses share boundary"


def test_resume_checks_blob_existence_without_downloading(monkeypatch):
    ids = trip()
    with pytest.raises(RuntimeError):
        migrate.migrate_subtree(ME, ids["R"], f"shares/{ids['R']}", kind="share", mode="rw", crash_after="blobs")
    past = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)).isoformat()
    db.partition_ref(ME).collection("meta").document("rev").update(
        {"migrating.lease_until": past, "migrating.step": "frozen"})
    store = blobstore.get_store()
    monkeypatch.setattr(store, "get", lambda key: pytest.fail("downloaded a blob to check it exists"))
    assert migrate.resume_if_stale(ME) is True
    assert store.exists(f"shares/{ids['R']}/todos/{ids['C1']}/img1")
