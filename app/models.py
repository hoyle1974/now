from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Literal, get_args
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, Field, RootModel, field_serializer, field_validator


def utc_now() -> datetime.datetime:
    """Now in UTC as a naive datetime: the form every stored timestamp already
    has (a server clock in another timezone must not leak into the data), and
    naive and aware values can't be compared, so the form must not change."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class TodoId(RootModel[uuid.UUID]):
    def __str__(self) -> str:
        return str(self.root)

class Repeat(BaseModel):
    """Repeat rule: every `every` units. "weekday" means the next Mon-Fri day."""
    unit: Literal["day", "weekday", "week", "month", "year"]
    every: int = Field(1, ge=1, le=999)
Color = Literal["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"]
COLORS = get_args(Color)
ItemType = Literal["todo", "list", "project"]  # keep in step with app/types.json
MAX_LINKS = 20
MAX_URL_LEN = 2048
MAX_LABEL_LEN = 200
MAX_REFS = 50
# Generous, but a Firestore document is capped at 1 MiB: refuse absurd input with
# a 422 rather than let the write fail as a 500.
MAX_TITLE_LEN = 2000
MAX_SPLIT_ITEMS = 100

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
    title: str = Field(max_length=MAX_TITLE_LEN)
    color: Color | None = Field(None)  # the client picks one so it can show it at once; omitted = server picks
    due_date: datetime.datetime | None = Field(None)
    type: ItemType | None = Field(None)  # omitted = todo

class TodoUpdate(BaseModel):
    title: str | None = Field(None, max_length=MAX_TITLE_LEN)
    done: bool | None = Field(None)
    due_date: datetime.datetime | None = Field(None)
    deleted: bool | None = Field(None)
    collapsed: bool | None = Field(None)
    repeat: Repeat | None = Field(None)  # an explicit null clears the rule
    color: Color | None = Field(None)          # explicit null clears
    type: ItemType | None = Field(None)        # only the label changes; due_date, repeat and done stay
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
    descriptions: list[Annotated[str, Field(max_length=MAX_TITLE_LEN)]] = Field([], max_length=MAX_SPLIT_ITEMS)
    due_date: datetime.datetime | None = Field(None)
    type: ItemType | None = Field(None)  # applies to every child created; omitted = todo

class Todo(BaseModel):
    todo_id: TodoId = Field(default_factory=lambda: TodoId(uuid4()) )
    title: str  # unbounded on read: a stored todo must always load
    done: bool = Field(False)
    create_date: datetime.datetime = Field(default_factory=utc_now)
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
    type: ItemType = Field("todo")
    links: list[Link] = Field([])
    blocked_by: list[TodoId] = Field([])
    references: list[TodoId] = Field([])
    attachments: list[Attachment] = Field([])  # only changed via the attachment endpoints
    blocked: bool = Field(False)  # derived, never stored; only filled in by get_tree

    @field_serializer("create_date", when_used="json")
    def _create_date_as_utc(self, v: datetime.datetime) -> str:
        # Stored naive but always UTC: say so on the wire ("Z"), or a browser reads
        # the bare string as its own local time. due_date stays bare on purpose: it
        # is the user's wall-clock time, not an instant.
        return v.isoformat() + "Z" if v.tzinfo is None else v.isoformat()
