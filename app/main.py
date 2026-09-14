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

@app.post("/tasks", response_model=models.TODO)
def create_task(body: models.TODOCreate) -> models.TODO:
    t = models.TODO(title = body.title)
    db.createTODO(t)
    return t

def _print_task(indent:int, todo: models.TODO) -> None:
    print(f"{'':>{indent * 2}}{todo.title} Create:{todo.create_date} Due:{todo.due_date} [{'done' if todo.done else 'not done'}]")
    for child_id in todo.child_ids:
        _print_task(indent+1, db.getTODO(child_id))

@app.get("/tasks/print", response_model=None)
def print_all_tasks() -> None:
    for t in db.getRootTasks():
        _print_task(0,t)


@app.get("/tasks/root", response_model=list[models.TODO])
def list_tasks() -> list[models.TODO]:
    return db.getRootTasks()


@app.get("/tasks/{task_id}", response_model=models.TODO)
def get_task(task_id: uuid.UUID) -> models.TODO:
    todo =  db.getTODO(models.GenericId(task_id))

    if todo is None:
        raise HTTPException(404)

    return todo

@app.patch("/tasks/{task_id}", response_model=models.TODO)
def update_task(task_id: uuid.UUID, body: models.TODOUpdate) -> models.TODO:
    todo = db.getTODO(models.GenericId(task_id))

    if todo is None:
        raise HTTPException(404)

    if body.title is not None:
        todo.title = body.title
    if body.done is not None: 
        todo.done = body.done

    db.updateTODO(todo)

    return todo

@app.patch("/tasks/{task_id}/parent/{parent_id}", response_model=models.TODO)
def update_task_parent(task_id: uuid.UUID, body: models.TODOUpdateParent) -> models.TODO:
    todo = db.getTODO(models.GenericId(task_id))
    if todo is None:
        raise HTTPException(404)

    result =  db.updateParentId(todo, body.parent_id)
    if result is None:
        raise HTTPException(404)

    return result


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID) -> None:
    db.deleteTODO(models.GenericId(task_id))

@app.post("/tasks/{task_id}/split", response_model=models.TODO)
def split_task(task_id: uuid.UUID, body: models.TODOSplit) -> models.TODO:
    todo = db.getTODO(models.GenericId(task_id))

    if todo is None:
        raise HTTPException(404)

    return db.splitIntoChildren(todo, body.descriptions) 

    

