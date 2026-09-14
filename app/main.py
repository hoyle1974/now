from __future__ import annotations
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, HTTPException
import uuid
from app import db
from app import models

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Routes go here.

db.init()

@app.post("/todos", response_model=models.Todo)
def create_todo(body: models.TodoCreate) -> models.Todo:
    todo = models.Todo(title = body.title)
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


@app.get("/todos/{todo_id}", response_model=models.Todo)
def get_todo(todo_id: uuid.UUID) -> models.Todo:
    todo =  db.get_todo(models.GenericId(todo_id))

    if todo is None:
        raise HTTPException(404)

    return todo

@app.patch("/todos/{todo_id}", response_model=models.Todo)
def update_todo(todo_id: uuid.UUID, body: models.TodoUpdate) -> models.Todo:
    todo = db.get_todo(models.GenericId(todo_id))

    if todo is None:
        raise HTTPException(404)

    if body.title is not None:
        todo.title = body.title
    if body.done is not None:
        todo.done = body.done

    db.update_todo(todo)

    return todo

@app.patch("/todos/{todo_id}/parent/{parent_id}", response_model=models.Todo)
def update_todo_parent(todo_id: uuid.UUID, body: models.TodoUpdateParent) -> models.Todo:
    todo = db.get_todo(models.GenericId(todo_id))
    if todo is None:
        raise HTTPException(404)

    result =  db.update_parent_id(todo, body.parent_id)
    if result is None:
        raise HTTPException(404)

    return result


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: uuid.UUID) -> None:
    db.delete_todo(models.GenericId(todo_id))

@app.post("/todos/{todo_id}/split", response_model=models.Todo)
def split_todo(todo_id: uuid.UUID, body: models.TodoSplit) -> models.Todo:
    todo = db.get_todo(models.GenericId(todo_id))

    if todo is None:
        raise HTTPException(404)

    return db.split_into_children(todo, body.descriptions)



