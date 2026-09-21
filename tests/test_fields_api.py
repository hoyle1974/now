import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import db, models
from app.auth import require_user

app.dependency_overrides[require_user] = lambda: None

c = TestClient(app)

@pytest.fixture(autouse=True)
def db_setup():
    db.init()
    for name in ("todos", "todos_archive", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield
    db.teardown()

def mk(title="t"):
    return c.post("/todos", json={"title": title}).json()

def patch(t, **body):
    return c.patch(f"/todos/{t['todo_id']}", json=body)

def test_defaults():
    t = mk()
    assert t["color"] in models.COLORS and t["links"] == [] and t["blocked_by"] == [] and t["references"] == []

def test_new_root_gets_random_color():
    root = mk()
    assert root["color"] in models.COLORS

def test_color_set_clear_invalid():
    t = mk()
    assert patch(t, color="teal").json()["color"] == "teal"
    assert c.get(f"/todos/{t['todo_id']}").json()["color"] == "teal"
    assert patch(t, color=None).json()["color"] is None
    assert patch(t, color="mauve").status_code == 422

def test_links():
    t = mk()
    r = patch(t, links=[{"url": "https://a.com/x", "label": "A"}, {"url": "http://b.org"}])
    assert r.json()["links"] == [{"url": "https://a.com/x", "label": "A"}, {"url": "http://b.org", "label": None}]
    assert patch(t, links=[{"url": "javascript:alert(1)"}]).status_code == 422
    assert patch(t, links=[{"url": "ftp://x.com"}]).status_code == 422
    assert patch(t, links=[{"url": "https://a.com"}] * 21).status_code == 422
    assert patch(t, links=[]).json()["links"] == []

def test_refs_validation():
    a, b = mk(), mk()
    assert patch(a, references=[a["todo_id"]]).status_code == 400
    assert patch(a, blocked_by=[a["todo_id"]]).status_code == 400
    assert patch(a, references=["00000000-0000-4000-8000-000000000000"]).status_code == 400
    assert patch(a, references=[b["todo_id"], b["todo_id"]]).json()["references"] == [b["todo_id"]]
    assert patch(a, blocked_by=[b["todo_id"]]).status_code == 200
    assert patch(b, blocked_by=[a["todo_id"]]).status_code == 400
    x, y, z = mk(), mk(), mk()
    patch(x, blocked_by=[y["todo_id"]])
    patch(y, blocked_by=[z["todo_id"]])
    assert patch(z, blocked_by=[x["todo_id"]]).status_code == 400
    assert patch(b, references=[a["todo_id"]]).status_code == 200  # refs may be mutual

def test_blocked_derived_in_tree():
    a, b = mk(), mk()
    patch(a, blocked_by=[b["todo_id"]])
    def node():
        return c.get("/todos/tree").json()["todosById"][a["todo_id"]]
    assert node()["blocked"] is True
    patch(b, done=True)
    assert node()["blocked"] is False
    patch(b, done=False)
    assert node()["blocked"] is True
    c.delete(f"/todos/{b['todo_id']}")
    assert node()["blocked"] is False
    assert node()["blocked_by"] == [b["todo_id"]]  # id kept
    c.patch(f"/todos/{b['todo_id']}/undelete")
    assert node()["blocked"] is True

def test_if_match_and_version_bump():
    t = mk()
    r = c.patch(f"/todos/{t['todo_id']}", json={"color": "red"}, headers={"If-Match": "99"})
    assert r.status_code == 409
    r = c.patch(f"/todos/{t['todo_id']}", json={"color": "red"}, headers={"If-Match": str(t["version"])})
    assert r.json()["version"] == t["version"] + 1


def test_blocked_by_rejects_ancestors_and_descendants():
    parent, kid, grandkid, other = mk("p"), mk("k"), mk("g"), mk("o")
    c.patch(f"/todos/{kid['todo_id']}/reparent", json={"parent_id": parent["todo_id"]})
    c.patch(f"/todos/{grandkid['todo_id']}/reparent", json={"parent_id": kid["todo_id"]})
    assert patch(parent, blocked_by=[kid["todo_id"]]).status_code == 400      # own subtask
    assert patch(parent, blocked_by=[grandkid["todo_id"]]).status_code == 400  # deeper subtask
    assert patch(grandkid, blocked_by=[parent["todo_id"]]).status_code == 400  # own ancestor
    assert patch(kid, blocked_by=[other["todo_id"]]).status_code == 200        # unrelated is fine
    assert patch(kid, references=[parent["todo_id"]]).status_code == 200       # references may relate

def _archive(t):
    import datetime
    c.delete(f"/todos/{t['todo_id']}")
    db.archive_expired(now=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=31))

def test_archived_link_ids_stay_editable():
    a, b, gone, fresh = mk(), mk(), mk(), mk()
    assert patch(a, blocked_by=[gone["todo_id"]], references=[gone["todo_id"]]).status_code == 200
    _archive(gone)
    # An id already on the todo is kept even though its target was archived.
    r = patch(a, blocked_by=[gone["todo_id"], b["todo_id"]], references=[gone["todo_id"], fresh["todo_id"]])
    assert r.status_code == 200, r.text
    assert r.json()["blocked_by"] == [gone["todo_id"], b["todo_id"]]
    # A newly added unknown/archived id is still rejected.
    assert patch(b, references=[gone["todo_id"]]).status_code == 400
    # Self-reference stays rejected.
    assert patch(a, references=[gone["todo_id"], a["todo_id"]]).status_code == 400
    # Dropping the dead id works.
    assert patch(a, blocked_by=[b["todo_id"]]).json()["blocked_by"] == [b["todo_id"]]
