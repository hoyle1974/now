"""The permissions matrix (tests/fixtures/share_rules.json) against the real routes.
Every (action, role) pair: allowed → 2xx, denied → 403 (404 where the caller has no mount)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import blobstore, db
from app.main import app
from tests.helpers import OTHER_USER, TEST_USER, act_as, wipe_users
from tests.share_fixtures import CHILD, ROOT, make_share

RULES = json.loads((Path(__file__).parent / "fixtures" / "share_rules.json").read_text())
client = TestClient(app)
H = {"X-Share": ROOT}

# role -> (caller, make_share kwargs); the owner is always TEST_USER.
ROLES = {
    "owner":    (TEST_USER, dict(mode="ro", mount_for=(TEST_USER,))),
    "rw":       (OTHER_USER, dict(mode="rw", mount_for=(TEST_USER, OTHER_USER))),
    "ro":       (OTHER_USER, dict(mode="ro", mount_for=(TEST_USER, OTHER_USER))),
    "stranger": (OTHER_USER, dict(mode="rw", members=[TEST_USER], mount_for=(TEST_USER,))),
    "revoked":  (OTHER_USER, dict(mode="rw", state="unshared", returned_to=TEST_USER, mount_for=(OTHER_USER,))),
}

ACTIONS = {
    "read":         lambda: client.get(f"/todos/{CHILD}", headers=H),
    "collapse":     lambda: client.patch(f"/todos/{CHILD}", json={"collapsed": True}, headers=H),
    "edit_child":   lambda: client.patch(f"/todos/{CHILD}", json={"title": "x"}, headers=H),
    "check_child":  lambda: client.patch(f"/todos/{CHILD}", json={"done": True}, headers=H),
    "add_child":    lambda: client.post(f"/todos/{ROOT}/split", json={"descriptions": ["x"]}, headers=H),
    "delete_child": lambda: client.delete(f"/todos/{CHILD}", headers=H),
    "edit_root":    lambda: client.patch(f"/todos/{ROOT}", json={"title": "x"}, headers=H),
    "delete_root":  lambda: client.delete(f"/todos/{ROOT}", headers=H),
    "change_mode":  lambda: client.put(f"/todos/{ROOT}/share", json={"mode": "rw"}),
    "unshare":      lambda: client.delete(f"/todos/{ROOT}/share"),
    "move_mount":   lambda: client.patch(f"/todos/{ROOT}/reparent", json={"parent_id": None, "index": 0}),
    "drag_across":  lambda: client.patch(f"/todos/{CHILD}/reparent",
                                         json={"parent_id": None, "index": 0, "parent_share": None}, headers=H),
}

# Rows whose routes arrive with the share routes (plan Task 7).
LATER: set[str] = set()


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("SHARING_ENABLED", "1")
    db.init()
    wipe_users()
    blobstore.use_memory()
    yield
    app.dependency_overrides.clear()
    db.teardown()


CASES = [(a, r) for a in RULES["actions"] for r in RULES["roles"]]


@pytest.mark.parametrize("action,role", CASES, ids=[f"{a}-{r}" for a, r in CASES])
def test_share_rule(action, role, request):
    if action in LATER:
        request.applymarker(pytest.mark.xfail(reason="route lands in Task 7", strict=False))
    caller, kwargs = ROLES[role]
    make_share(TEST_USER, **kwargs)
    act_as(app, caller)
    r = ACTIONS[action]()
    if RULES["actions"][action][role]:
        assert 200 <= r.status_code < 300, f"{action}/{role}: {r.status_code} {r.text}"
    else:
        assert r.status_code in (403, 404), f"{action}/{role}: {r.status_code} {r.text}"
