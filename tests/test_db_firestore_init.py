import pytest
from app import db
from unittest.mock import patch, MagicMock

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
