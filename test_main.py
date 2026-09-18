"""Tests for the todo API endpoints.

Run with: pytest test_main.py -v

Stub only -- imports and test function names are set up, bodies are
yours to fill in.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import db
import uuid

client = TestClient(app)

@pytest.fixture
def db_setup():
    # setup code runs here
    db.init(memory=True)
    yield 0
    db.teardown()

@pytest.fixture
def create_test_data():
    response1 = client.post("/todos", json={"title": "test1"})

    d = response1.json()
    id = d["todo_id"]
    d["title"] = "test1"
    d["done"] = False
    d["parent_id"] = None

    response2 = client.post("/todos", json={"title": "test2"})
    parent_id = response2.json()["todo_id"]

    d["parent_id"] = parent_id
    response3 = client.patch(f"/todos/{id}/parent/{parent_id}", json=d)

    response4 = client.get(f"/todos/{id}")

    response5 = client.get(f"/todos/{parent_id}")

    response6 = client.get(f"/todos/root")

    response7 = client.post(f"/todos/{id}/split", json={"descriptions": ["a","b","c","d"]})
    yield 0
    

def test_create_todo(db_setup):
    response = client.post("/todos", json={"title": "test"})

    assert response.status_code == 200
    assert response.json()["title"] == "test"
    assert response.json()["done"] == False


def test_get_todo(db_setup):
    response1 = client.post("/todos", json={"title": "test"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test"
    assert response1.json()["done"] == False

    id = response1.json()["todo_id"]
    response2 = client.get(f"/todos/{id}")
    assert response2.status_code == 200

    assert response1.json() == response2.json()


def test_get_todo_not_found(db_setup):
    id = uuid.uuid4()
    response = client.get(f"/todos/{id}")
    assert response.status_code == 404


def test_update_todo(db_setup):
    response1 = client.post("/todos", json={"title": "test"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test"
    assert response1.json()["done"] == False
 
    d = response1.json()
    id = d["todo_id"]
    d["title"] = "test2"
    d["done"] = True
    d["parent_id"] = None

    response2 = client.patch(f"/todos/{id}", json=d)
    assert response2.status_code == 200

    response3 = client.get(f"/todos/{id}")
    assert response3.status_code == 200

    assert response3.json() == d


def test_update_todo_not_found(db_setup):
    id = uuid.uuid4()

    d={}
    d["todo_id"] = str(id)
    d["title"] = "test2"
    d["done"] = True
    d["parent_id"] = None

    response2 = client.patch(f"/todos/{str(id)}", json=d)
    assert response2.status_code == 404

def test_split_todo(db_setup):
    response1 = client.post("/todos", json={"title": "Big Task"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "Big Task"
    assert response1.json()["done"] == False

    id = response1.json()["todo_id"]
    response2 = client.post(f"/todos/{id}/split", json={"descriptions": ["a","b","c","d"]})
    assert response2.status_code == 200


def test_update_todo_parent(db_setup):
    response1 = client.post("/todos", json={"title": "test1"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test1"
    assert response1.json()["done"] == False

    d = response1.json()
    id = d["todo_id"]
    d["title"] = "test1"
    d["done"] = False
    d["parent_id"] = None

    response2 = client.post("/todos", json={"title": "test2"})
    assert response2.status_code == 200
    assert response2.json()["title"] == "test2"
    assert response2.json()["done"] == False
    parent_id = response2.json()["todo_id"]

    d["parent_id"] = parent_id
    response3 = client.patch(f"/todos/{id}/parent/{parent_id}", json=d)
    assert response3.status_code == 200

    response4 = client.get(f"/todos/{id}")
    assert response4.status_code == 200

    assert response3.json() == d

    response5 = client.get(f"/todos/{parent_id}")
    assert response5.status_code == 200
    assert response5.json()["child_ids"] == [ id ]

    response6 = client.get(f"/todos/root")
    assert response6.status_code == 200
    assert response6.json()[0]["todo_id"] == parent_id


def test_delete_todo(db_setup):
    response1 = client.post("/todos", json={"title": "test"})
    assert response1.status_code == 200
    assert response1.json()["title"] == "test"
    assert response1.json()["done"] == False
    id = response1.json()["todo_id"]

    response2 = client.delete(f"/todos/{id}")
    assert response2.status_code == 204

    response3 = client.get(f"/todos/{id}")
    assert response3.status_code == 404

def test_print(db_setup, create_test_data):
    response = client.get("/todos/print")
    assert response.status_code == 200


def test_root_serves_frontend_shell(db_setup):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Todos</title>" in response.text


