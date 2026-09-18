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
    raise NotImplementedError("Firestore create_todo")

def delete_todo(todo_id: models.TodoId):
    """Soft delete a todo and its subtree"""
    raise NotImplementedError("Firestore delete_todo")

def reorder_todo(todo_id: models.TodoId, direction: str):
    """Move a todo up or down within its siblings"""
    raise NotImplementedError("Firestore reorder_todo")

def undelete_todo(todo_id: models.TodoId):
    """Restore a soft-deleted todo and its entire subtree"""
    raise NotImplementedError("Firestore undelete_todo")

def update_todo(todo: models.Todo, cascade_done: bool = False):
    """Update a todo, optionally cascading done status to children"""
    raise NotImplementedError("Firestore update_todo")

def update_parent_id(todo: models.Todo, parent_id: models.TodoId | None) -> models.Todo | None:
    """Move a todo to a different parent"""
    raise NotImplementedError("Firestore update_parent_id")

def get_root_todos() -> list[models.Todo]:
    """Get all root-level todos (parent_id is None)"""
    raise NotImplementedError("Firestore get_root_todos")

def get_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a single todo by ID (excludes soft-deleted)"""
    raise NotImplementedError("Firestore get_todo")

def get_deleted_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a single todo by ID regardless of deleted status"""
    raise NotImplementedError("Firestore get_deleted_todo")

def split_into_children(todo: models.Todo, descriptions: list[str], due_date=None) -> models.Todo:
    """Create multiple child todos from descriptions"""
    raise NotImplementedError("Firestore split_into_children")
