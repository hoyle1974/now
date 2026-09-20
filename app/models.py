from __future__ import annotations
from pydantic import BaseModel,Field
from typing import Literal
from uuid import uuid4
import uuid
import datetime
from typing import Literal
from urllib.parse import urlparse
from pydantic import field_validator

from pydantic import RootModel
class TodoId(RootModel[uuid.UUID]):
    def __str__(self) -> str:
        return str(self.root)

class Repeat(BaseModel):
    """Repeat rule: every `every` units. "weekday" means the next Mon-Fri day."""
    unit: Literal["day", "weekday", "week", "month", "year"]
    every: int = Field(1, ge=1, le=999)
COLORS = ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink")
Color = Literal["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"]
MAX_LINKS = 20
MAX_URL_LEN = 2048
MAX_LABEL_LEN = 200
MAX_REFS = 50

class Link(BaseModel):
    url: str
    label: str | None = Field(None)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip()
        u = urlparse(v)
        if len(v) > MAX_URL_LEN or u.scheme not in ("http", "https") or not u.netloc:
            raise ValueError("url must be an http(s) URL under 2048 chars")
        return v

    @field_validator("label")
    @classmethod
    def _check_label(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_LABEL_LEN:
            raise ValueError("label too long")
        return v

MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

class Attachment(BaseModel):
    """Metadata for one image; the bytes live in the blob store."""
    id: str
    name: str
    content_type: str
    size: int

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
    color: Color | None = Field(None)          # explicit null clears
    links: list[Link] | None = Field(None)     # replaces the whole list
    blocked_by: list[TodoId] | None = Field(None)  # replaces the whole list
    references: list[TodoId] | None = Field(None)  # replaces the whole list

    @field_validator("links")
    @classmethod
    def _cap_links(cls, v):
        if v is not None and len(v) > MAX_LINKS:
            raise ValueError(f"at most {MAX_LINKS} links")
        return v

    @field_validator("blocked_by", "references")
    @classmethod
    def _dedupe_ids(cls, v):
        if v is None:
            return v
        out = list(dict.fromkeys(str(i) for i in v))
        if len(out) > MAX_REFS:
            raise ValueError(f"at most {MAX_REFS} ids")
        return [TodoId(uuid.UUID(i)) for i in out]

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
    # When it was soft-deleted (UTC); None while live or for todos deleted before this was kept.
    deleted_at: datetime.datetime | None = Field(None)
    collapsed: bool = Field(False)
    repeat: Repeat | None = Field(None)
    # Set by the server once this todo has spawned its next occurrence, so a
    # todo repeats at most once however often it is ticked and unticked.
    spawned_id: TodoId | None = Field(None)
    version: int = Field(1)
    color: Color | None = Field(None)
    links: list[Link] = Field([])
    blocked_by: list[TodoId] = Field([])
    references: list[TodoId] = Field([])
    attachments: list[Attachment] = Field([])  # only changed via the attachment endpoints
    blocked: bool = Field(False)  # derived, never stored; only filled in by get_tree
