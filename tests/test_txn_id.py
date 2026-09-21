import datetime
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import db
from app.auth import require_user

app.dependency_overrides[require_user] = lambda: None
c = TestClient(app)


@pytest.fixture(autouse=True)
def setup():
    db.init()
    for name in ("todos", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield
    db.teardown()


@pytest.mark.parametrize("bad", ["a/b", "__x__", "a b", "a.b", "x" * 101])
def test_unsafe_txn_id_rejected(bad):
    r = c.post("/todos", json={"title": "t"}, headers={"X-Txn-Id": bad})
    assert r.status_code == 400
    assert c.get("/todos/rev").status_code == 200


def test_real_client_ids_accepted_and_idempotent():
    h = {"X-Txn-Id": "3f2b8c1e-9a4d-4c7e-8b1f-0123456789ab"}
    a = c.post("/todos", json={"title": "t"}, headers=h)
    b = c.post("/todos", json={"title": "t"}, headers=h)
    assert a.status_code == 200 and a.json() == b.json()


def test_txn_log_retention_outlasts_offline_devices():
    h = {"X-Txn-Id": "old-1"}
    c.post("/todos", json={"title": "t"}, headers=h)
    ref = db.get_conn().collection("txn_log").document("old-1")
    ref.update({"created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)})
    assert db.prune_txn_log() == 0
    ref.update({"created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31)})
    assert db.prune_txn_log() == 1


def test_api_reads_are_never_cached_by_the_browser():
    for path in ("/todos/next", "/todos/tree", "/todos/rev"):
        r = c.get(path)
        assert r.headers.get("cache-control") == "no-store", path
