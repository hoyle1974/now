import pytest
from app import db, models, tenant
from tests.helpers import TEST_USER
from unittest.mock import patch, MagicMock
import uuid
import datetime


@pytest.fixture(autouse=True)
def bind_user():
    # These tests mock the Firestore client itself, but user_ref() still needs a
    # bound user to build its users/{email} path.
    token = tenant.set_user(TEST_USER)
    yield
    tenant.reset(token)


@patch('app.db_firestore.firestore.Client')
def test_init_creates_connection(mock_firestore_client):
    """Test that init() creates Firestore connection"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection

    db.init()

    mock_firestore_client.assert_called_once()
    db.teardown()

@patch('app.db_firestore.firestore.Client')
def test_get_conn_returns_client(mock_firestore_client):
    """Test that get_conn() returns the Firestore client"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection

    db.init()
    conn = db.get_conn()
    assert conn is mock_client
    db.teardown()

@patch('app.db_firestore.firestore.Client')
def test_create_todo(mock_firestore_client):
    """Test creating a todo"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_doc_ref = MagicMock()

    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.collection.return_value = mock_collection  # users/{email}.collection("todos")

    db.init()
    todo = models.Todo(title="Test task")
    db.create_todo(todo)

    mock_doc_ref.set.assert_called_once()
    call_args = mock_doc_ref.set.call_args[0][0]
    assert call_args["title"] == "Test task"
    assert call_args["done"] == False
    db.teardown()

@patch('app.db_firestore.firestore.Client')
def test_get_todo(mock_firestore_client):
    """Test retrieving a todo"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()

    todo_id = uuid.uuid4()
    doc_data = {
        "todo_id": str(todo_id),
        "title": "Test task",
        "done": False,
        "create_date": datetime.datetime.now().isoformat(),
        "due_date": None,
        "order_idx": None,
        "parent_id": None,
        "deleted": False
    }

    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.collection.return_value = mock_collection  # users/{email}.collection("todos")
    mock_doc_ref.get.return_value = mock_doc_snapshot
    mock_doc_snapshot.exists = True
    mock_doc_snapshot.to_dict.return_value = doc_data
    mock_collection.where.return_value.where.return_value.order_by.return_value.get.return_value = []

    db.init()
    retrieved = db.get_todo(models.TodoId(todo_id))

    assert retrieved is not None
    assert retrieved.title == "Test task"
    assert retrieved.done == False
    db.teardown()

@patch('app.db_firestore.firestore.Client')
def test_get_deleted_todo(mock_firestore_client):
    """Test retrieving a deleted todo"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()
    
    todo_id = uuid.uuid4()
    doc_data = {
        "todo_id": str(todo_id),
        "title": "Deleted task",
        "done": False,
        "create_date": datetime.datetime.now().isoformat(),
        "due_date": None,
        "order_idx": None,
        "parent_id": None,
        "deleted": True
    }
    
    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.collection.return_value = mock_collection  # users/{email}.collection("todos")
    mock_doc_ref.get.return_value = mock_doc_snapshot
    mock_doc_snapshot.exists = True
    mock_doc_snapshot.to_dict.return_value = doc_data
    mock_collection.where.return_value.order_by.return_value.get.return_value = []

    db.init()

    retrieved = db.get_deleted_todo(models.TodoId(todo_id))
    
    assert retrieved is not None
    assert retrieved.title == "Deleted task"
    assert retrieved.deleted == True
    
    db.teardown()
