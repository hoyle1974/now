from app import models
import uuid
import datetime

def doc_to_todo(doc_dict: dict) -> models.Todo:
    """Convert Firestore document dict to Todo model"""
    return models.Todo(
        todo_id=models.TodoId(uuid.UUID(doc_dict["todo_id"])),
        title=doc_dict["title"],
        done=doc_dict.get("done", False),
        create_date=datetime.datetime.fromisoformat(doc_dict["create_date"]),
        due_date=None if doc_dict.get("due_date") is None else datetime.datetime.fromisoformat(doc_dict["due_date"]),
        order_idx=doc_dict.get("order_idx"),
        parent_id=None if doc_dict.get("parent_id") is None else models.TodoId(uuid.UUID(doc_dict["parent_id"])),
        deleted=doc_dict.get("deleted", False),
        child_ids=[]
    )

def todo_to_doc(todo: models.Todo) -> dict:
    """Convert Todo model to Firestore document dict"""
    return {
        "todo_id": str(todo.todo_id),
        "title": todo.title,
        "done": todo.done,
        "create_date": todo.create_date.isoformat(),
        "due_date": None if todo.due_date is None else todo.due_date.isoformat(),
        "order_idx": todo.order_idx,
        "parent_id": None if todo.parent_id is None else str(todo.parent_id),
        "deleted": todo.deleted
    }

def get_subtree_ids(todos_collection, parent_id: str) -> list[str]:
    """Recursively get all descendant IDs for a todo"""
    ids = []
    children = todos_collection.where("parent_id", "==", parent_id).get()
    for child_doc in children:
        child_id = child_doc.to_dict()["todo_id"]
        ids.append(child_id)
        ids.extend(get_subtree_ids(todos_collection, child_id))
    return ids
