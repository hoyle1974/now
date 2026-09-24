import datetime
import uuid

from app import models, types


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
        deleted_at=(None if doc_dict.get("deleted_at") is None
                    else datetime.datetime.fromisoformat(doc_dict["deleted_at"])),
        collapsed=doc_dict.get("collapsed", False),
        repeat=doc_dict.get("repeat"),
        spawned_id=None if doc_dict.get("spawned_id") is None else models.TodoId(uuid.UUID(doc_dict["spawned_id"])),
        # Docs written before versioning existed have no field: treat as version 1.
        version=doc_dict.get("version", 1),
        color=doc_dict.get("color"),
        # Documents from before types have none; an unknown value must never break a read.
        type=doc_dict["type"] if doc_dict.get("type") in types.NAMES else types.DEFAULT,
        priority=doc_dict["priority"] if doc_dict.get("priority") in ("high", "normal", "low") else "normal",
        links=[models.Link(**link) for link in doc_dict.get("links") or []],
        blocked_by=[models.TodoId(uuid.UUID(i)) for i in doc_dict.get("blocked_by") or []],
        references=[models.TodoId(uuid.UUID(i)) for i in doc_dict.get("references") or []],
        attachments=[models.Attachment(**a) for a in doc_dict.get("attachments") or []],
        calendar_url=doc_dict.get("calendar_url"),
        location=doc_dict.get("location"),
        end_date=None if doc_dict.get("end_date") is None else datetime.datetime.fromisoformat(doc_dict["end_date"]),
        notes=doc_dict.get("notes"),
        repeat_summary=doc_dict.get("repeat_summary"),
        conference_url=doc_dict.get("conference_url"),
        attendees=[models.Attendee(**a) for a in doc_dict.get("attendees") or []],
        external_uid=doc_dict.get("external_uid"),
        last_synced_at=(None if doc_dict.get("last_synced_at") is None
                        else datetime.datetime.fromisoformat(doc_dict["last_synced_at"])),
        last_sync_error=doc_dict.get("last_sync_error"),
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
        "deleted": todo.deleted,
        "deleted_at": None if todo.deleted_at is None else todo.deleted_at.isoformat(),
        "collapsed": todo.collapsed,
        "repeat": None if todo.repeat is None else todo.repeat.model_dump(),
        "spawned_id": None if todo.spawned_id is None else str(todo.spawned_id),
        "version": todo.version,
        "color": todo.color,
        "type": todo.type,
        "priority": todo.priority,
        "links": [{"url": link.url, "label": link.label} for link in todo.links],
        "blocked_by": [str(i) for i in todo.blocked_by],
        "references": [str(i) for i in todo.references],
        "attachments": [a.model_dump() for a in todo.attachments],
        "calendar_url": todo.calendar_url,
        "location": todo.location,
        "end_date": None if todo.end_date is None else todo.end_date.isoformat(),
        "notes": todo.notes,
        "repeat_summary": todo.repeat_summary,
        "conference_url": todo.conference_url,
        "attendees": [a.model_dump() for a in todo.attendees],
        "external_uid": todo.external_uid,
        "last_synced_at": None if todo.last_synced_at is None else todo.last_synced_at.isoformat(),
        "last_sync_error": todo.last_sync_error,
    }

def get_subtree_docs(todos_collection, parent_id: str, getter=None) -> list[dict]:
    """All descendant documents (as dicts) of a todo, deleted or not.

    getter runs a query; pass one that joins the current Firestore transaction
    so the reads are part of it.
    """
    getter = getter or (lambda query: query.get())
    docs = []
    for child_doc in getter(todos_collection.where("parent_id", "==", parent_id)):
        data = child_doc.to_dict()
        docs.append(data)
        docs.extend(get_subtree_docs(todos_collection, data["todo_id"], getter))
    return docs
