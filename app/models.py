from __future__ import annotations
from pydantic import BaseModel,Field
from uuid import uuid4
import uuid
import datetime

from pydantic import RootModel
class GenericId(RootModel[uuid.UUID]):
    def __str__(self) -> str:
        return str(self.root)

class TODOCreate(BaseModel):
    title: str

class TODOUpdate(BaseModel):
    title: str | None = Field(None)
    done: bool | None = Field(None)

class TODOUpdateParent(BaseModel):
    parent_id: GenericId | None = Field(None)

class TODOSplit(BaseModel):
    descriptions: list[str] = Field([])

class TODO(BaseModel):
    todo_id: GenericId = Field(default_factory=lambda: GenericId(uuid4()) )
    title: str
    done: bool = Field(False)
    create_date: datetime.datetime = Field(default_factory = datetime.datetime.now)
    due_date: datetime.datetime | None = Field(None)
    order_idx: int | None = Field(None)
    parent_id: GenericId | None = Field(None)
    child_ids: list[GenericId] = Field([])
