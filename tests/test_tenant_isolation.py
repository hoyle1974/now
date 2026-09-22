import pytest
from fastapi.testclient import TestClient

from app import blobstore, db, tenant
from app.main import app
from tests.helpers import OTHER_USER, TEST_USER, act_as, wipe_users

client = TestClient(app)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def setup():
    db.init()
    wipe_users()
    blobstore.use_memory()
    yield
    app.dependency_overrides.clear()
    db.teardown()


def test_one_users_todos_are_invisible_to_another():
    act_as(app, TEST_USER)
    made = client.post("/todos", json={"title": "mine"}).json()
    act_as(app, OTHER_USER)
    assert "mine" not in client.get("/todos/root").text
    assert client.get(f"/todos/{made['todo_id']}").status_code == 404
    act_as(app, TEST_USER)
    assert "mine" in client.get("/todos/root").text


def test_each_user_has_their_own_revision_counter():
    act_as(app, TEST_USER)
    client.post("/todos", json={"title": "a"})
    client.post("/todos", json={"title": "b"})
    rev_me = client.get("/todos/rev").json()
    act_as(app, OTHER_USER)
    assert client.get("/todos/rev").json() != rev_me


def test_a_txn_id_is_not_replayed_across_users():
    act_as(app, TEST_USER)
    first = client.post("/todos", json={"title": "mine"}, headers={"X-Txn-Id": "same-id"}).json()
    act_as(app, OTHER_USER)
    second = client.post("/todos", json={"title": "theirs"}, headers={"X-Txn-Id": "same-id"}).json()
    assert second["title"] == "theirs"
    assert second["todo_id"] != first["todo_id"]


def test_an_unbound_data_call_raises_instead_of_picking_a_user():
    with pytest.raises(RuntimeError):
        db.get_rev()


def test_documents_live_under_users_email():
    with tenant.as_user(TEST_USER):
        client_ = TestClient(app)
        act_as(app, TEST_USER)
        made = client_.post("/todos", json={"title": "x"}).json()
    ref = db.user_ref(TEST_USER).collection("todos").document(made["todo_id"])
    assert ref.get().exists
    assert not db.get_conn().collection("todos").document(made["todo_id"]).get().exists


def test_blob_keys_are_per_user():
    with tenant.as_user(TEST_USER):
        a = blobstore.key_for("t1", "a1")
    with tenant.as_user(OTHER_USER):
        b = blobstore.key_for("t1", "a1")
    assert a == "users/me@example.com/todos/t1/a1"
    assert b == "users/other@example.com/todos/t1/a1"


def test_prune_txn_log_covers_every_user():
    import datetime
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)
    for email in (TEST_USER, OTHER_USER):
        db.user_ref(email).collection("txn_log").document("old").set({"created_at": old})
    assert db.prune_txn_log() == 2


def test_another_user_cannot_patch_your_todo():
    act_as(app, TEST_USER)
    made = client.post("/todos", json={"title": "mine"}).json()
    act_as(app, OTHER_USER)
    r = client.patch(f"/todos/{made['todo_id']}", json={"title": "hijacked"},
                      headers={"If-Match": str(made["version"])})
    assert r.status_code == 404
    act_as(app, TEST_USER)
    assert client.get(f"/todos/{made['todo_id']}").json()["title"] == "mine"


def test_another_user_cannot_delete_your_todo():
    act_as(app, TEST_USER)
    made = client.post("/todos", json={"title": "mine"}).json()
    act_as(app, OTHER_USER)
    # DELETE is idempotent-by-design (204 even for an id that doesn't exist for this
    # user), so the isolation proof is that A's todo survives, not the status code.
    r = client.delete(f"/todos/{made['todo_id']}")
    assert r.status_code == 204
    act_as(app, TEST_USER)
    again = client.get(f"/todos/{made['todo_id']}")
    assert again.status_code == 200
    assert again.json()["deleted"] is False


def test_another_user_cannot_undelete_or_reparent_your_todo():
    act_as(app, TEST_USER)
    made = client.post("/todos", json={"title": "mine"}).json()
    client.delete(f"/todos/{made['todo_id']}")
    act_as(app, OTHER_USER)
    assert client.patch(f"/todos/{made['todo_id']}/undelete").status_code == 404
    assert client.patch(f"/todos/{made['todo_id']}/reparent",
                        json={"parent_id": None, "index": 0}).status_code == 404


def test_another_user_cannot_touch_your_attachments():
    act_as(app, TEST_USER)
    made = client.post("/todos", json={"title": "mine"}).json()
    up = client.post(f"/todos/{made['todo_id']}/attachments",
                     files={"file": ("pic.png", PNG, "image/png")})
    assert up.status_code == 200
    attachment_id = up.json()["attachments"][0]["id"]

    act_as(app, OTHER_USER)
    assert client.get(f"/todos/{made['todo_id']}/attachments/{attachment_id}").status_code == 404
    assert client.delete(f"/todos/{made['todo_id']}/attachments/{attachment_id}").status_code == 404
    assert client.post(f"/todos/{made['todo_id']}/attachments",
                       files={"file": ("pic2.png", PNG, "image/png")}).status_code == 404

    act_as(app, TEST_USER)
    still = client.get(f"/todos/{made['todo_id']}/attachments/{attachment_id}")
    assert still.status_code == 200


def test_another_users_tree_next_and_trash_are_empty_while_yours_has_data():
    act_as(app, TEST_USER)
    due_soon = client.post("/todos", json={"title": "due soon", "due_date": "2020-01-01T00:00:00Z"}).json()
    trashed = client.post("/todos", json={"title": "trashed"}).json()
    client.delete(f"/todos/{trashed['todo_id']}")

    act_as(app, OTHER_USER)
    tree = client.get("/todos/tree").json()
    assert tree["roots"] == [] and tree["todosById"] == {}
    assert client.get("/todos/next").json()["items"] == []
    trash = client.get("/todos/trash").json()
    assert trash["items"] == []

    act_as(app, TEST_USER)
    assert client.get("/todos/tree").json()["roots"]
    assert client.get("/todos/next").json()["items"]
    assert client.get("/todos/trash").json()["items"]
    assert due_soon["todo_id"]  # sanity: fixture actually created both todos
