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


def as_utc_instant(v: datetime.datetime | None) -> str | None:
    """A stored UTC instant for the wire, always with `Z`. Naive means UTC.
    Without a marker a browser reads the digits as its own local time.
    Wall-clock fields (due_date, end_date) must not use this."""
    if v is None:
        return None
    if v.tzinfo is not None:
        v = v.astimezone(datetime.UTC).replace(tzinfo=None)
    return v.isoformat() + "Z"


class TodoId(RootModel[uuid.UUID]):
    def __str__(self) -> str:
        return str(self.root)

class Repeat(BaseModel):
    """Repeat rule: every `every` units. "weekday" means the next Mon-Fri day."""
    unit: Literal["day", "weekday", "week", "month", "year"]
    every: int = Field(1, ge=1, le=999)
Color = Literal["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"]
COLORS = get_args(Color)
Priority = Literal["high", "normal", "low"]
ItemType = Literal["todo", "list", "project", "note", "calendar", "calendar_event", "mount"]  # keep in step with app/types.json
# What a request may set: every type except the server-managed mount (types.USER_NAMES).
UserItemType = Literal["todo", "list", "project", "note", "calendar", "calendar_event"]
MAX_LINKS = 20
MAX_URL_LEN = 2048
MAX_LABEL_LEN = 200
MAX_REFS = 50
# Generous, but a Firestore document is capped at 1 MiB: refuse absurd input with
# a 422 rather than let the write fail as a 500.
MAX_TITLE_LEN = 2000
MAX_SPLIT_ITEMS = 100
# A note body. Well under Firestore's 1 MiB document cap, attachments metadata included.
MAX_CONTENT_LEN = 100_000

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

AttendeeStatus = Literal["accepted", "declined", "tentative", "needs-action"]
# Caps for what a calendar sync copies in, so one huge invite can't push a document past 1 MiB.
MAX_NOTES_LEN = 10_000
MAX_ATTENDEES = 200

class Attendee(BaseModel):
    """One guest on a synced calendar event (ICS ATTENDEE), as the feed reported them."""
    name: str | None = Field(None)
    email: str | None = Field(None)
    status: AttendeeStatus = Field("needs-action")
    organizer: bool = Field(False)

class TodoCreate(BaseModel):
    title: str = Field(max_length=MAX_TITLE_LEN)
    color: Color | None = Field(None)  # the client picks one so it can show it at once; omitted = server picks
    due_date: datetime.datetime | None = Field(None)
    type: UserItemType | None = Field(None)  # omitted = todo

class TodoUpdate(BaseModel):
    # Omitted = leave alone. Explicit null clears ONLY due_date, repeat, color and calendar_url
    # (update_todo checks model_fields_set); on every other field null == omitted.
    title: str | None = Field(None, max_length=MAX_TITLE_LEN)
    done: bool | None = Field(None)
    due_date: datetime.datetime | None = Field(None)
    deleted: bool | None = Field(None)
    collapsed: bool | None = Field(None)
    repeat: Repeat | None = Field(None)  # explicit null clears the rule
    color: Color | None = Field(None)  # explicit null clears
    type: UserItemType | None = Field(None)        # only the label changes; due_date, repeat and done stay
    calendar_url: str | None = Field(None, max_length=MAX_URL_LEN)  # explicit null clears
    links: list[Link] | None = Field(None)     # replaces the whole list
    blocked_by: list[TodoId] | None = Field(None)  # replaces the whole list
    references: list[TodoId] | None = Field(None)  # replaces the whole list
    priority: Priority | None = Field(None)  # high | normal | low; omitted leaves it alone
    content: str | None = Field(None, max_length=MAX_CONTENT_LEN)  # note body; "" or null clears

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

    @field_validator("calendar_url")
    @classmethod
    def _check_calendar_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        u = urlparse(v)
        if not v or u.scheme not in ("http", "https") or not u.netloc:
            raise ValueError("calendar_url must be an http(s) URL")
        return v

class TodoReparent(BaseModel):
    parent_id: TodoId | None = Field(None)  # null moves to the top level
    index: int | None = Field(None)         # position among the new siblings; null = last
    # Partition of the new parent: a share id, or null for your own list. Omitted = the todo's own.
    parent_share: str | None = Field(None, pattern=r"^[A-Za-z0-9-]{1,64}$")

class TodoRepeatRequest(BaseModel):
    today: datetime.date | None = Field(None)  # the client's local date; server date if omitted

class SyncNowBody(BaseModel):
    client_session_id: str | None = Field(None, max_length=64)

class TodoSplit(BaseModel):
    descriptions: list[Annotated[str, Field(max_length=MAX_TITLE_LEN)]] = Field([], max_length=MAX_SPLIT_ITEMS)
    due_date: datetime.datetime | None = Field(None)
    type: UserItemType | None = Field(None)  # applies to every child created; omitted = todo
    # Applied only when one child is created and that type has a content field.
    content: str | None = Field(None, max_length=MAX_CONTENT_LEN)

class ShareTag(BaseModel):
    """Derived on a tree read for every node that comes from a share; never stored."""
    id: str
    mode: Literal["ro", "rw"]
    owner: str


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
    priority: Priority = Field("normal")  # user-owned; a calendar sync never copies or clears it
    links: list[Link] = Field([])
    content: str | None = Field(None)  # note body; kept when the type changes, same as a dormant due date
    blocked_by: list[TodoId] = Field([])
    references: list[TodoId] = Field([])
    attachments: list[Attachment] = Field([])  # only changed via the attachment endpoints
    calendar_url: str | None = Field(None)  # calendar type: the source ICS feed URL
    location: str | None = Field(None)      # calendar_event type: from the source ICS event
    # calendar_event type, all copied from the source ICS event by the sync (never user-edited):
    end_date: datetime.datetime | None = Field(None)  # floating wall-clock like due_date; all-day = exclusive midnight
    notes: str | None = Field(None)            # DESCRIPTION, as plain text
    repeat_summary: str | None = Field(None)   # the series' RRULE in words ("Weekly on Mon"); None = one-off
    conference_url: str | None = Field(None)   # video-call link
    attendees: list[Attendee] = Field([])
    external_uid: str | None = Field(None)  # calendar_event type: stable id from the source feed, for sync matching
    last_synced_at: datetime.datetime | None = Field(None)  # calendar type: server-managed
    last_sync_error: str | None = Field(None)  # calendar type: server-managed
    blocked: bool = Field(False)  # derived, never stored; only filled in by get_tree
    last_edited_by: str | None = Field(None)  # email of the last writer; set only inside a share
    share: ShareTag | None = Field(None)      # derived, never stored: this node comes from a share
    share_root: bool = Field(False)           # derived, never stored: the share's root (merged with your mount)

    @field_serializer("create_date", "deleted_at", "last_synced_at", when_used="json")
    def _instants_as_utc(self, v: datetime.datetime | None) -> str | None:
        # due_date and end_date stay bare: they are the user's wall-clock time.
        return as_utc_instant(v)


class ShareRequest(BaseModel):
    mode: Literal["ro", "rw"]
