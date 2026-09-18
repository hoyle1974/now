from __future__ import annotations
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import uuid
from app import db
from app import models

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Routes go here.

db.init()

@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run"""
    return {"status": "ok"}

@app.post("/todos", response_model=models.Todo)
def create_todo(body: models.TodoCreate) -> models.Todo:
    todo = models.Todo(title = body.title)
    if body.due_date:
        todo.due_date = body.due_date
    db.create_todo(todo)
    return todo

def _print_todo(indent:int, todo: models.Todo) -> None:
    print(f"{'':>{indent * 2}}{todo.title} Create:{todo.create_date} Due:{todo.due_date} [{'done' if todo.done else 'not done'}]")
    for child_id in todo.child_ids:
        _print_todo(indent+1, db.get_todo(child_id))

@app.get("/todos/print", response_model=None)
def print_all_todos() -> None:
    for todo in db.get_root_todos():
        _print_todo(0,todo)


@app.get("/todos/root", response_model=list[models.Todo])
def list_todos() -> list[models.Todo]:
    return db.get_root_todos()

@app.get("/todos/tree", response_model=dict)
def get_tree() -> dict:
    """Get the full todo tree in one request: { roots: [...], todosById: {...} }"""
    roots = db.get_root_todos()
    todosById = {}

    def collect_tree(todo):
        todosById[str(todo.todo_id)] = todo
        for child_id in todo.child_ids:
            child = db.get_todo(child_id)
            if child:
                collect_tree(child)

    for root in roots:
        collect_tree(root)

    return {
        "roots": roots,
        "todosById": todosById
    }


@app.get("/todos/{todo_id}", response_model=models.Todo)
def get_todo(todo_id: uuid.UUID) -> models.Todo:
    todo =  db.get_todo(models.TodoId(todo_id))

    if todo is None:
        raise HTTPException(404)

    return todo

@app.patch("/todos/{todo_id}", response_model=models.Todo)
def update_todo(todo_id: uuid.UUID, body: models.TodoUpdate) -> models.Todo:
    todo = db.get_todo(models.TodoId(todo_id))

    if todo is None:
        raise HTTPException(404)

    if body.title is not None:
        todo.title = body.title
    if body.done is not None:
        todo.done = body.done
    if body.due_date is not None:
        todo.due_date = body.due_date
    if body.deleted is not None:
        todo.deleted = body.deleted

    db.update_todo(todo, cascade_done=body.done is not None)

    return todo

@app.patch("/todos/{todo_id}/parent/{parent_id}", response_model=models.Todo)
def update_todo_parent(todo_id: uuid.UUID, body: models.TodoUpdateParent) -> models.Todo:
    todo = db.get_todo(models.TodoId(todo_id))
    if todo is None:
        raise HTTPException(404)

    result =  db.update_parent_id(todo, body.parent_id)
    if result is None:
        raise HTTPException(404)

    return result


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: uuid.UUID) -> None:
    # Soft delete - mark as deleted instead of removing
    todo = db.get_todo(models.TodoId(todo_id))
    if todo:
        todo.deleted = True
        db.update_todo(todo)

@app.patch("/todos/{todo_id}/undelete", response_model=models.Todo)
def undelete_todo_endpoint(todo_id: uuid.UUID) -> models.Todo:
    """Restore a soft-deleted todo and its entire subtree (undo)"""
    todo = db.get_deleted_todo(models.TodoId(todo_id))
    if todo is None:
        raise HTTPException(404)
    # Undelete the entire subtree
    db.undelete_todo(models.TodoId(todo_id))
    # Return the restored todo (need to reload to get the latest state)
    restored = db.get_todo(models.TodoId(todo_id))
    return restored if restored else todo

@app.post("/todos/{todo_id}/split", response_model=models.Todo)
def split_todo(todo_id: uuid.UUID, body: models.TodoSplit) -> models.Todo:
    todo = db.get_todo(models.TodoId(todo_id))

    if todo is None:
        raise HTTPException(404)

    return db.split_into_children(todo, body.descriptions, body.due_date)

@app.patch("/todos/{todo_id}/move/{direction}", response_model=models.Todo)
def move_todo(todo_id: uuid.UUID, direction: str) -> models.Todo:
    """Move a todo up or down within its parent's children (direction: 'up' or 'down')"""
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")

    todo = db.get_todo(models.TodoId(todo_id))
    if todo is None or todo.parent_id is None:
        raise HTTPException(404, "todo not found or has no parent")

    try:
        db.reorder_todo(models.TodoId(todo_id), direction)
    except Exception as e:
        raise HTTPException(400, f"Cannot move: {str(e)}")

    # Return the updated todo
    updated = db.get_todo(models.TodoId(todo_id))
    return updated if updated else todo


app.mount("/", StaticFiles(directory="web", html=True), name="web")

