"""Item types: registry, model, and every guard that reads a capability."""
import datetime as dt
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app import db, ics, models, push, tasks, types
from app.db_firestore_helpers import doc_to_todo, todo_to_doc
from app.main import app
from app.next_up import rank_next_up

client = TestClient(app)


@pytest.fixture
def db_setup():
    db.init()
    for name in ("todos", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield
    db.teardown()


# ---- registry ---------------------------------------------------------------

def test_registry_has_the_three_types_and_flags():
    assert set(types.NAMES) == {"todo", "list", "project"}
    flags = {"hasCheckbox", "appearsInNextUp", "triggersAutodone", "countsInBadge", "showsProgress", "notifies"}
    for name in types.NAMES:
        assert flags <= set(types.caps(name))
        assert "title" in types.caps(name)["fields"]


def test_unknown_or_missing_type_falls_back_to_todo():
    assert types.caps(None) == types.caps("todo")
    assert types.caps("nonsense") == types.caps("todo")
    assert types.can_type("todo", "hasCheckbox") is True
    assert types.can_type("list", "hasCheckbox") is False
    assert types.can_type("project", "showsProgress") is True


# ---- model, storage, PATCH --------------------------------------------------

def test_model_literal_matches_registry():
    assert set(get_args(models.ItemType)) == set(types.NAMES)


def test_doc_round_trip_and_defaults():
    t = models.Todo(title="x", type="project")
    assert todo_to_doc(t)["type"] == "project"
    assert doc_to_todo(todo_to_doc(t)).type == "project"
    old = todo_to_doc(models.Todo(title="old"))
    del old["type"]
    assert doc_to_todo(old).type == "todo"          # documents from before types
    old["type"] = "from-the-future"
    assert doc_to_todo(old).type == "todo"          # unknown never breaks a read


def test_patch_type_keeps_other_fields(db_setup):
    r = client.post("/todos", json={"title": "a", "due_date": "2026-09-30T00:00:00"})
    tid, v = r.json()["todo_id"], r.json()["version"]
    assert r.json()["type"] == "todo"
    r = client.patch(f"/todos/{tid}", json={"type": "list"}, headers={"If-Match": str(v)})
    assert r.status_code == 200 and r.json()["type"] == "list"
    assert r.json()["due_date"] == "2026-09-30T00:00:00"      # kept, just inactive
    assert client.get(f"/todos/{tid}").json()["type"] == "list"
    assert client.patch(f"/todos/{tid}", json={"type": "bogus"}).status_code == 422
