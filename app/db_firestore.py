# Firestore implementation of todo database
from __future__ import annotations
from app import models
from app import db_firestore_helpers
import uuid
import datetime
from google.cloud import firestore

_client = None
_todos_collection = None

def init(memory: bool = False):
    """Initialize Firestore connection"""
    global _client, _todos_collection
    _client = firestore.Client()
    _todos_collection = _client.collection("todos")
    print("firestore: initialized")

def get_conn():
    """Return Firestore client"""
    global _client
    return _client

def teardown():
    """Cleanup Firestore connection"""
    global _client, _todos_collection
    if _client is not None:
        _client.close()
    _client = None
    _todos_collection = None

def create_todo(todo: models.Todo):
    """Create a new todo in Firestore"""
    global _todos_collection

    doc_data = db_firestore_helpers.todo_to_doc(todo)
    _todos_collection.document(str(todo.todo_id)).set(doc_data)

def delete_todo(todo_id: models.TodoId):
    """Soft delete a todo and its subtree"""
    global _todos_collection

    descendant_ids = db_firestore_helpers.get_subtree_ids(
        _todos_collection, str(todo_id)
    )
    descendant_ids.insert(0, str(todo_id))

    for desc_id in descendant_ids:
        _todos_collection.document(desc_id).update({"deleted": True})

def reorder_todo(todo_id: models.TodoId, direction: str):
    """Move a todo up or down within its siblings"""
    global _todos_collection

    if direction not in ("up", "down"):
        raise Exception("direction must be 'up' or 'down'")

    todo_doc = _todos_collection.document(str(todo_id)).get()
    if not todo_doc.exists:
        raise Exception("Todo not found")

    todo_data = todo_doc.to_dict()
    parent_id = todo_data.get("parent_id")

    if not parent_id:
        raise Exception("Cannot reorder root todos")

    sibling_docs = _todos_collection.where("parent_id", "==", parent_id).where("deleted", "==", False).order_by("order_idx").get()
    siblings = [(doc.to_dict()["todo_id"], doc.to_dict().get("order_idx")) for doc in sibling_docs]

    if len(siblings) < 2:
        raise Exception("Cannot move: no siblings to swap with")

    current_pos = next((i for i, (sid, _) in enumerate(siblings) if sid == str(todo_id)), None)
    if current_pos is None:
        raise Exception("Todo not in sibling list")

    if direction == "up":
        if current_pos == 0:
            raise Exception("Already at top")
        new_pos = current_pos - 1
    else:
        if current_pos == len(siblings) - 1:
            raise Exception("Already at bottom")
        new_pos = current_pos + 1

    moving_id = siblings[current_pos][0]
    siblings.pop(current_pos)
    siblings.insert(new_pos, (moving_id, siblings[new_pos][1] if new_pos < len(siblings) else None))

    for idx, (sibling_id, _) in enumerate(siblings):
        _todos_collection.document(sibling_id).update({"order_idx": idx})

def undelete_todo(todo_id: models.TodoId):
    """Restore a soft-deleted todo and its entire subtree"""
    global _todos_collection

    descendant_ids = db_firestore_helpers.get_subtree_ids(
        _todos_collection, str(todo_id)
    )
    descendant_ids.insert(0, str(todo_id))

    for desc_id in descendant_ids:
        _todos_collection.document(desc_id).update({"deleted": False})

    # Assign order_idx if needed
    todo_doc = _todos_collection.document(str(todo_id)).get()
    todo_data = todo_doc.to_dict()
    if todo_data.get("parent_id") and todo_data.get("order_idx") is None:
        parent_id = todo_data["parent_id"]
        sibling_docs = _todos_collection.where("parent_id", "==", parent_id).where("deleted", "==", False).get()
        max_idx = max([doc.to_dict().get("order_idx", -1) for doc in sibling_docs] or [-1])
        _todos_collection.document(str(todo_id)).update({"order_idx": max_idx + 1})

def update_todo(todo: models.Todo, cascade_done: bool = False):
    """Update a todo, optionally cascading done status to children"""
    global _todos_collection

    doc_data = db_firestore_helpers.todo_to_doc(todo)
    _todos_collection.document(str(todo.todo_id)).update(doc_data)

    if cascade_done:
        descendant_ids = db_firestore_helpers.get_subtree_ids(
            _todos_collection, str(todo.todo_id)
        )
        for desc_id in descendant_ids:
            _todos_collection.document(desc_id).update({"done": todo.done})

def update_parent_id(todo: models.Todo, parent_id: models.TodoId | None) -> models.Todo | None:
    """Move a todo to a different parent"""
    global _todos_collection

    order_idx = todo.order_idx
    if parent_id and order_idx is None:
        sibling_docs = _todos_collection.where("parent_id", "==", str(parent_id)).where("deleted", "==", False).get()
        max_idx = max([doc.to_dict().get("order_idx", -1) for doc in sibling_docs] or [-1])
        order_idx = max_idx + 1

    _todos_collection.document(str(todo.todo_id)).update({
        "parent_id": None if parent_id is None else str(parent_id),
        "order_idx": order_idx
    })

    todo.parent_id = parent_id
    todo.order_idx = order_idx
    return todo

def get_root_todos() -> list[models.Todo]:
    """Get all root-level todos (parent_id is None)"""
    global _todos_collection

    docs = _todos_collection.where("parent_id", "==", None).where("deleted", "==", False).order_by("order_idx").get()

    todos = []
    for doc in docs:
        data = doc.to_dict()
        todo = db_firestore_helpers.doc_to_todo(data)

        # Populate children
        children_docs = _todos_collection.where("parent_id", "==", str(todo.todo_id)).where("deleted", "==", False).order_by("order_idx").get()
        child_ids = [models.TodoId(uuid.UUID(c.to_dict()["todo_id"])) for c in children_docs]
        todo.child_ids = child_ids

        todos.append(todo)

    return todos

def get_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a single todo by ID (excludes soft-deleted)"""
    global _todos_collection

    doc = _todos_collection.document(str(todo_id)).get()
    if not doc.exists:
        return None

    data = doc.to_dict()
    if data.get("deleted", False):
        return None

    todo = db_firestore_helpers.doc_to_todo(data)

    # Populate children
    children_docs = _todos_collection.where("parent_id", "==", str(todo_id)).where("deleted", "==", False).order_by("order_idx").get()
    child_ids = [models.TodoId(uuid.UUID(c.to_dict()["todo_id"])) for c in children_docs]
    todo.child_ids = child_ids

    return todo

def get_deleted_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a single todo by ID regardless of deleted status"""
    global _todos_collection

    doc = _todos_collection.document(str(todo_id)).get()
    if not doc.exists:
        return None

    data = doc.to_dict()
    todo = db_firestore_helpers.doc_to_todo(data)

    # Populate children (including deleted)
    children_docs = _todos_collection.where("parent_id", "==", str(todo_id)).order_by("order_idx").get()
    child_ids = [models.TodoId(uuid.UUID(c.to_dict()["todo_id"])) for c in children_docs]
    todo.child_ids = child_ids

    return todo

def split_into_children(todo: models.Todo, descriptions: list[str], due_date=None) -> models.Todo:
    """Create multiple child todos from descriptions"""
    global _todos_collection

    children_docs = _todos_collection.where("parent_id", "==", str(todo.todo_id)).where("deleted", "==", False).get()
    max_idx = max([doc.to_dict().get("order_idx", -1) for doc in children_docs] or [-1])
    next_order = max_idx + 1

    for description in descriptions:
        child_todo = models.Todo(
            title=description,
            parent_id=todo.todo_id,
            order_idx=next_order,
            due_date=due_date
        )
        doc_data = db_firestore_helpers.todo_to_doc(child_todo)
        _todos_collection.document(str(child_todo.todo_id)).set(doc_data)
        next_order += 1

    return get_todo(todo.todo_id)
