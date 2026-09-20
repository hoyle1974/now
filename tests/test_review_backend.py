"""Backend review findings: move errors, attachment blob cleanup, archive safety,
naive/aware timestamps, upload size guard."""
import datetime
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import db, blobstore, models, next_up
from app import db_firestore
from app.auth import require_user

app.dependency_overrides[require_user] = lambda: None
c = TestClient(app)
c500 = TestClient(app, raise_server_exceptions=False)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
UTC = datetime.timezone.utc


@pytest.fixture(autouse=True)
def setup():
    db.init()
    for name in ("todos", "todos_archive", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    blobstore.use_memory()
    yield
    db.teardown()


def mk(title="t"):
    return c.post("/todos", json={"title": title}).json()


def upload(todo, **kw):
    return c.post(f"/todos/{todo['todo_id']}/attachments", files={"file": ("p.png", PNG, "image/png")}, **kw)


def ref(tid):
    return db.get_conn().collection("todos").document(tid)


# A. move errors -----------------------------------------------------------

def test_move_unexpected_error_is_not_a_400(monkeypatch):
    a, b = mk("a"), mk("b")

    def boom(*_a, **_k):
        raise RuntimeError("transient firestore trouble")
    monkeypatch.setattr(db_firestore, "_update", boom)
    assert c500.patch(f"/todos/{b['todo_id']}/move/up").status_code == 500


def test_move_deliberate_cases_stay_4xx():
    a, b = mk("a"), mk("b")
    assert c.patch(f"/todos/{a['todo_id']}/move/up").status_code == 400      # already at top
    assert c.patch(f"/todos/{b['todo_id']}/move/down").status_code == 400    # already at bottom
    assert c.patch(f"/todos/{a['todo_id']}/move/sideways").status_code == 400


# B. attachment blobs ------------------------------------------------------

def test_upload_blob_deleted_when_commit_fails(monkeypatch):
    t = mk()
    real = db.run_atomic

    def run_then_fail(txn_id, fn):
        fn()  # the attempt ran (used the blob) but its writes never committed
        raise RuntimeError("commit aborted")
    monkeypatch.setattr(db, "run_atomic", run_then_fail)
    monkeypatch.setattr(db, "update_todo", lambda *a, **k: None)
    assert c500.post(f"/todos/{t['todo_id']}/attachments",
                     files={"file": ("p.png", PNG, "image/png")}).status_code == 500
    monkeypatch.setattr(db, "run_atomic", real)
    assert blobstore.get_store().keys() == []


def test_upload_blob_kept_when_commit_actually_succeeded(monkeypatch):
    t = mk()
    real = db.run_atomic

    def commit_then_lose_connection(txn_id, fn):
        real(txn_id, fn)
        raise RuntimeError("response lost after commit")
    monkeypatch.setattr(db, "run_atomic", commit_then_lose_connection)
    c500.post(f"/todos/{t['todo_id']}/attachments", files={"file": ("p.png", PNG, "image/png")})
    monkeypatch.setattr(db, "run_atomic", real)
    [a] = c.get(f"/todos/{t['todo_id']}").json()["attachments"]
    assert blobstore.get_store().keys() == [blobstore.key_for(t["todo_id"], a["id"])]


def test_sweep_removes_only_old_unreferenced_blobs():
    t = mk()
    a = upload(t).json()["attachments"][0]
    store = blobstore.get_store()
    tid = t["todo_id"]
    orphan = blobstore.key_for(tid, "orphan")
    fresh = blobstore.key_for(tid, "fresh")
    gone = blobstore.key_for("00000000-0000-0000-0000-000000000000", "x")
    for k in (orphan, fresh, gone):
        store.put(k, b"x", "image/png")
    long_ago = datetime.datetime.now(UTC) - datetime.timedelta(days=2)
    for k in (orphan, gone, blobstore.key_for(tid, a["id"])):
        store._times[k] = long_ago
    assert db.sweep_orphan_blobs() == 2
    assert store.keys() == sorted([fresh, blobstore.key_for(tid, a["id"])])
    assert db.sweep_orphan_blobs() == 0


def test_archive_deletes_blobs_of_purged_todos_even_without_attachment_field():
    t = mk()
    upload(t)
    c.delete(f"/todos/{t['todo_id']}")
    ref(t["todo_id"]).update({"deleted_at": (datetime.datetime.now(UTC) - datetime.timedelta(days=40)).isoformat()})
    assert db.archive_expired() == 1
    assert blobstore.get_store().keys() == []


# C. legacy parent route is gone -------------------------------------------

def test_legacy_parent_route_removed():
    a, b = mk("a"), mk("b")
    r = c.patch(f"/todos/{a['todo_id']}/parent/{b['todo_id']}", json={"parent_id": b["todo_id"]})
    assert r.status_code in (404, 405)
    assert not hasattr(db, "update_parent_id") and not hasattr(db, "delete_todo")


# D. archive races ---------------------------------------------------------

def _old_delete(tid, days=40):
    c.delete(f"/todos/{tid}")
    ref(tid).update({"deleted_at": (datetime.datetime.now(UTC) - datetime.timedelta(days=days)).isoformat()})


def test_archive_skips_todo_undeleted_after_it_was_read(monkeypatch):
    t = mk()
    _old_delete(t["todo_id"])
    real = db_firestore.db_firestore_helpers.get_subtree_docs

    def undelete_meanwhile(*a, **k):
        out = real(*a, **k)
        ref(t["todo_id"]).update({"deleted": False, "deleted_at": None})
        return out
    monkeypatch.setattr(db_firestore.db_firestore_helpers, "get_subtree_docs", undelete_meanwhile)
    assert db.archive_expired() == 0
    assert ref(t["todo_id"]).get().exists
    assert not db.get_conn().collection("todos_archive").document(t["todo_id"]).get().exists


def test_archive_bumps_rev_when_it_moves_something():
    t = mk()
    _old_delete(t["todo_id"])
    before = db.get_rev()
    assert db.archive_expired() == 1
    assert db.get_rev() > before


def test_archive_run_claim_is_exclusive():
    now = datetime.datetime.now(UTC)
    assert db_firestore._claim_archive_run(now) is True
    assert db_firestore._claim_archive_run(now + datetime.timedelta(minutes=1)) is False
    assert db_firestore._claim_archive_run(now + datetime.timedelta(days=2)) is True


# E. naive / aware timestamps ----------------------------------------------

def test_archive_handles_naive_deleted_at():
    t = mk()
    c.delete(f"/todos/{t['todo_id']}")
    ref(t["todo_id"]).update({"deleted_at": "2020-01-01T00:00:00"})
    assert db.archive_expired() == 1


def test_next_up_mixes_naive_and_aware_due_dates():
    naive = models.Todo(title="naive", due_date=datetime.datetime(2030, 1, 2, 9, 0))
    aware = models.Todo(title="aware", due_date=datetime.datetime(2030, 1, 1, 9, 0, tzinfo=UTC))
    none = models.Todo(title="none")
    by_id = {str(t.todo_id): t for t in (naive, aware, none)}
    items = next_up.rank_next_up([naive, aware, none], by_id)
    assert [i["title"] for i in items] == ["aware", "naive", "none"]


# G. upload size guard -------------------------------------------------------

def test_upload_rejected_early_by_content_length():
    t = mk()
    r = c.post(f"/todos/{t['todo_id']}/attachments", files={"file": ("p.png", PNG, "image/png")},
               headers={"content-length": str(models.MAX_ATTACHMENT_BYTES * 3)})
    assert r.status_code == 413
    assert c.get(f"/todos/{t['todo_id']}").json()["attachments"] == []


# 404 detail text (the client tells "todo gone" from a route 404 by it) ------

MISSING = "00000000-0000-0000-0000-000000000000"


def test_missing_todo_404s_say_todo_not_found():
    for r in (c.get(f"/todos/{MISSING}"),
              c.patch(f"/todos/{MISSING}", json={"title": "x"}),
              c.patch(f"/todos/{MISSING}/move/up"),
              c.patch(f"/todos/{MISSING}/reparent", json={"parent_id": None}),
              c.get(f"/todos/{MISSING}/attachments/abc"),
              c.post(f"/todos/{MISSING}/attachments", files={"file": ("p.png", PNG, "image/png")})):
        assert r.status_code == 404 and r.json()["detail"] == "todo not found", r.request.url
    # DELETE of a missing todo is an idempotent 204, not a 404.
    assert c.delete(f"/todos/{MISSING}").status_code == 204


def test_missing_attachment_and_parent_404s_are_distinct():
    t = mk()
    r = c.get(f"/todos/{t['todo_id']}/attachments/nope")
    assert r.status_code == 404 and r.json()["detail"] == "attachment not found"
    r = c.delete(f"/todos/{t['todo_id']}/attachments/nope")
    assert r.status_code == 404 and r.json()["detail"] == "attachment not found"
    r = c.patch(f"/todos/{t['todo_id']}/reparent", json={"parent_id": MISSING})
    assert r.status_code == 404 and r.json()["detail"] == "parent not found"
