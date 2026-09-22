import datetime
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import db, blobstore, models, tenant
from app.auth import require_user
from tests.helpers import TEST_USER, act_as, wipe_users

c = TestClient(app)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


@pytest.fixture(autouse=True)
def setup():
    act_as(app)
    db.init()
    wipe_users()
    token = tenant.set_user(TEST_USER)
    blobstore.use_memory()
    yield
    tenant.reset(token)
    db.teardown()


def mk(title="t"):
    return c.post("/todos", json={"title": title}).json()


def upload(todo, data=PNG, name="pic.png", ctype="image/png", **kw):
    return c.post(f"/todos/{todo['todo_id']}/attachments", files={"file": (name, data, ctype)}, **kw)


def test_upload_then_download_roundtrip():
    t = mk()
    r = upload(t)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == t["version"] + 1
    [a] = body["attachments"]
    assert a["name"] == "pic.png" and a["content_type"] == "image/png" and a["size"] == len(PNG)
    g = c.get(f"/todos/{t['todo_id']}/attachments/{a['id']}")
    assert g.status_code == 200 and g.content == PNG
    assert g.headers["content-type"] == "image/png"
    assert g.headers["x-content-type-options"] == "nosniff"
    assert g.headers["content-disposition"].startswith("inline")
    assert "immutable" in g.headers["cache-control"] and "private" in g.headers["cache-control"]


def test_upload_persists_on_todo_and_tree():
    t = mk()
    a = upload(t).json()["attachments"][0]
    assert c.get(f"/todos/{t['todo_id']}").json()["attachments"] == [a]
    assert c.get("/todos/tree").json()["todosById"][t["todo_id"]]["attachments"] == [a]


def test_upload_bumps_rev():
    t = mk()
    before = c.get("/todos/rev").json()["rev"]
    upload(t)
    assert c.get("/todos/rev").json()["rev"] == before + 1


@pytest.mark.parametrize("data,ctype", [(JPEG, "image/jpeg"), (GIF, "image/gif"), (WEBP, "image/webp")])
def test_allowed_types_use_sniffed_type(data, ctype):
    t = mk()
    # The client's claimed type is ignored.
    a = upload(t, data=data, name="x", ctype="application/octet-stream").json()["attachments"][0]
    assert a["content_type"] == ctype


def test_rejects_non_images_and_svg_and_spoofed_type():
    t = mk()
    assert upload(t, data=b"<svg xmlns='http://www.w3.org/2000/svg'/>", name="a.svg", ctype="image/svg+xml").status_code == 400
    assert upload(t, data=b"<html><script>alert(1)</script>", name="a.png", ctype="image/png").status_code == 400
    assert upload(t, data=b"", name="a.png", ctype="image/png").status_code == 400
    assert c.get(f"/todos/{t['todo_id']}").json()["attachments"] == []


def test_size_cap():
    t = mk()
    big = PNG + b"\x00" * (10 * 1024 * 1024)
    assert upload(t, data=big).status_code == 413
    ok = PNG + b"\x00" * (10 * 1024 * 1024 - len(PNG))
    assert upload(t, data=ok).status_code == 200


def test_max_ten_per_todo():
    t = mk()
    for _ in range(10):
        assert upload(t).status_code == 200
    assert upload(t).status_code == 400
    assert len(c.get(f"/todos/{t['todo_id']}").json()["attachments"]) == 10


def test_stale_version_409_and_no_orphan_blob():
    t = mk()
    upload(t)  # version now 2
    r = upload(t, headers={"If-Match": "1"})
    assert r.status_code == 409
    assert len(blobstore.get_store().keys()) == 1


def test_missing_todo_404_and_no_blob():
    r = c.post("/todos/00000000-0000-4000-8000-000000000000/attachments",
               files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 404
    assert blobstore.get_store().keys() == []


def test_get_unknown_attachment_404():
    t = mk()
    assert c.get(f"/todos/{t['todo_id']}/attachments/nope").status_code == 404


def test_attachment_id_from_another_todo_404():
    a, b = mk("a"), mk("b")
    aid = upload(a).json()["attachments"][0]["id"]
    assert c.get(f"/todos/{b['todo_id']}/attachments/{aid}").status_code == 404


def test_delete_removes_metadata_and_blob():
    t = mk()
    aid = upload(t).json()["attachments"][0]["id"]
    r = c.delete(f"/todos/{t['todo_id']}/attachments/{aid}")
    assert r.status_code == 200 and r.json()["attachments"] == []
    assert blobstore.get_store().keys() == []
    assert c.get(f"/todos/{t['todo_id']}/attachments/{aid}").status_code == 404
    assert c.delete(f"/todos/{t['todo_id']}/attachments/{aid}").status_code == 404


def test_soft_delete_keeps_attachments_and_undelete_restores():
    t = mk()
    aid = upload(t).json()["attachments"][0]["id"]
    c.delete(f"/todos/{t['todo_id']}")
    assert len(blobstore.get_store().keys()) == 1
    c.patch(f"/todos/{t['todo_id']}/undelete")
    assert c.get(f"/todos/{t['todo_id']}/attachments/{aid}").status_code == 200


def test_patch_cannot_touch_attachments():
    t = mk()
    upload(t)
    r = c.patch(f"/todos/{t['todo_id']}", json={"title": "x", "attachments": []})
    assert len(r.json()["attachments"]) == 1


def test_recurring_clone_does_not_copy_attachments():
    t = mk()
    c.patch(f"/todos/{t['todo_id']}", json={"repeat": {"unit": "day", "every": 1},
                                             "due_date": "2026-01-01T00:00:00"})
    upload(t)
    r = c.post(f"/todos/{t['todo_id']}/repeat", json={"today": "2026-01-01"})
    new = c.get("/todos/tree").json()["todosById"]
    assert r.status_code == 200
    others = [x for k, x in new.items() if k != t["todo_id"]]
    assert others and all(x["attachments"] == [] for x in others)


def test_archive_purges_blobs_for_subtree():
    parent, child = mk("p"), mk("c")
    c.patch(f"/todos/{child['todo_id']}/reparent", json={"parent_id": parent["todo_id"], "index": None})
    upload(parent)
    upload(child)
    keep = mk("keep")
    upload(keep)
    c.delete(f"/todos/{parent['todo_id']}")
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=31)
    db.archive_expired()  # deleted just now: not due
    assert len(blobstore.get_store().keys()) == 3  # nothing due yet
    db.archive_expired(now=future)
    [left] = blobstore.get_store().keys()
    assert left.startswith(blobstore.todo_prefix(keep["todo_id"]))


def test_requires_auth():
    app.dependency_overrides.pop(require_user)
    try:
        t_id = "00000000-0000-4000-8000-000000000000"
        assert c.post(f"/todos/{t_id}/attachments", files={"file": ("a.png", PNG, "image/png")}).status_code == 401
        assert c.get(f"/todos/{t_id}/attachments/x").status_code == 401
        assert c.get(f"/todos/{t_id}/attachments/x", headers={"x-widget-token": "anything"}).status_code == 401
    finally:
        act_as(app)


def test_blobstore_memory_roundtrip_and_prefix_delete():
    s = blobstore.MemoryStore()
    s.put("todos/a/1", b"x", "image/png")
    s.put("todos/a/2", b"y", "image/png")
    s.put("todos/b/1", b"z", "image/png")
    assert s.get("todos/a/1") == (b"x", "image/png")
    assert s.get("nope") is None
    s.delete_prefix("todos/a/")
    assert s.keys() == ["todos/b/1"]
    s.delete("todos/b/1")
    s.delete("todos/b/1")  # idempotent
    assert s.keys() == []


def test_get_store_refuses_memory_on_cloud_run(monkeypatch):
    monkeypatch.setattr(blobstore, "_store", None)
    monkeypatch.delenv("ATTACHMENTS_BUCKET", raising=False)
    monkeypatch.setenv("K_SERVICE", "now")
    with pytest.raises(RuntimeError, match="ATTACHMENTS_BUCKET"):
        blobstore.get_store()
    monkeypatch.delenv("K_SERVICE")
    assert isinstance(blobstore.get_store(), blobstore.MemoryStore)
