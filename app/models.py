from __future__ import annotations
from pydantic import BaseModel,Field
from typing import Literal
from uuid import uuid4
import uuid
import datetime

from pydantic import RootModel
class TodoId(RootModel[uuid.UUID]):
    def __str__(self) -> str:
        return str(self.root)

class Repeat(BaseModel):
    """Repeat rule: every `every` units. "weekday" means the next Mon-Fri day."""
    unit: Literal["day", "weekday", "week", "month", "year"]
    every: int = Field(1, ge=1, le=999)

class TodoCreate(BaseModel):
    title: str
    due_date: datetime.datetime | None = Field(None)

class TodoUpdate(BaseModel):
    title: str | None = Field(None)
    done: bool | None = Field(None)
    due_date: datetime.datetime | None = Field(None)
    deleted: bool | None = Field(None)
    collapsed: bool | None = Field(None)
    repeat: Repeat | None = Field(None)  # an explicit null clears the rule

class TodoUpdateParent(BaseModel):
    parent_id: TodoId | None = Field(None)

class TodoReparent(BaseModel):
    parent_id: TodoId | None = Field(None)  # null moves to the top level
    index: int | None = Field(None)         # position among the new siblings; null = last

class TodoRepeatRequest(BaseModel):
    today: datetime.date | None = Field(None)  # the client's local date; server date if omitted

class TodoSplit(BaseModel):
    descriptions: list[str] = Field([])
    due_date: datetime.datetime | None = Field(None)

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
    collapsed: bool = Field(False)
    repeat: Repeat | None = Field(None)
    # Set by the server once this todo has spawned its next occurrence, so a
    # todo repeats at most once however often it is ticked and unticked.
    spawned_id: TodoId | None = Field(None)
    version: int = Field(1)
