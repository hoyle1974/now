from __future__ import annotations
from pydantic import BaseModel,Field
from uuid import uuid4
import uuid
import datetime

from pydantic import RootModel
class TodoId(RootModel[uuid.UUID]):
    def __str__(self) -> str:
        return str(self.root)

class TodoCreate(BaseModel):
    title: str

class TodoUpdate(BaseModel):
    title: str | None = Field(None)
    done: bool | None = Field(None)
    due_date: datetime.datetime | None = Field(None)

class TodoUpdateParent(BaseModel):
    parent_id: TodoId | None = Field(None)

class TodoSplit(BaseModel):
    descriptions: list[str] = Field([])

class Todo(BaseModel):
    todo_id: TodoId = Field(default_factory=lambda: TodoId(uuid4()) )
    title: str
    done: bool = Field(False)
    create_date: datetime.datetime = Field(default_factory = datetime.datetime.now)
    due_date: datetime.datetime | None = Field(None)
    order_idx: int | None = Field(None)
    parent_id: TodoId | None = Field(None)
    child_ids: list[TodoId] = Field([])
    deleted: bool = Field(False)
