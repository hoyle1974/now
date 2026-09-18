import pytest
from app import db, models
from unittest.mock import patch, MagicMock
import uuid
import datetime

@patch('app.db_firestore.firestore.Client')
def test_init_creates_connection(mock_firestore_client):
    """Test that init() creates Firestore connection"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection

    db.init(memory=False)

    # Verify Client was instantiated
    mock_firestore_client.assert_called_once()
    # Verify collection was retrieved
    mock_client.collection.assert_called_once_with("todos")

    # Cleanup
    db.teardown()

@patch('app.db_firestore.firestore.Client')
def test_teardown_closes_connection(mock_firestore_client):
    """Test that teardown() closes Firestore connection"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection

    db.init(memory=False)
    db.teardown()

    # Verify close was called
    mock_client.close.assert_called_once()

@patch('app.db_firestore.firestore.Client')
def test_get_conn_returns_client(mock_firestore_client):
    """Test that get_conn() returns the Firestore client"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_firestore_client.return_value = mock_client
    mock_client.collection.return_value = mock_collection

    db.init(memory=False)

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
    
    db.init()
    
    todo = models.Todo(title="Test task")
    db.create_todo(todo)
    
    # Verify set was called with the document data
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
    
    # Setup mock data
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
