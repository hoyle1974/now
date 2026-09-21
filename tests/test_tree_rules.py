"""Clear-completed and blocked rules, from tests/fixtures/tree_rules.json.

The client mirrors these rules in JS (Sync.clearableIds, Fields.isBlocked) so they work
offline; tests_js/tree-rules.test.js runs the same fixture, so a rule can't change on one
side only. To change a rule, change the fixture and both implementations."""
import json
import uuid
from pathlib import Path

import pytest

from app import db, models

CASES = json.loads((Path(__file__).parent / "fixtures" / "tree_rules.json").read_text())["cases"]
_NS = uuid.UUID("00000000-0000-0000-0000-00000000fade")


def _id(label: str) -> models.TodoId:
    return models.TodoId(uuid.uuid5(_NS, label))


@pytest.fixture
def clean_db():
    db.init()
    for name in ("todos", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield
    db.teardown()


def _load(nodes: list[dict]) -> None:
    for node in nodes:
        db.create_todo(models.Todo(
            todo_id=_id(node["id"]), title=node["id"], type=node["type"], done=node["done"],
            parent_id=_id(node["parent"]) if "parent" in node else None,
            blocked_by=[_id(b) for b in node.get("blocked_by", [])],
            deleted=node.get("deleted", False),
        ))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_tree_rules_match_the_shared_fixture(clean_db, case):
    _load(case["nodes"])
    _, by_id = db.get_tree()
    blocked = {label for label in (n["id"] for n in case["nodes"]) if str(_id(label)) in by_id
               and by_id[str(_id(label))].blocked}
    assert blocked == set(case["blocked"])
    cleared = {tid for tid, _version in db.clear_completed()}
    assert cleared == {str(_id(label)) for label in case["clearable"]}
