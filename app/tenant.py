"""Who the current request is, and whose data it works on.

Two bindings: the *user* (the signed-in email: identity, permissions, push devices)
and the *partition* (the data a db call touches: users/{email} by default, or
shares/{id} for a request on a shared item). Set once per request by
app.auth.bind_user / bind_partition, or around background work with as_user() /
as_partition(). Every Firestore path and blob key is derived from partition(); with
nobody bound it raises, so a forgotten binding fails loudly instead of touching the
wrong account."""
from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_user", default=None)
_partition: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_partition", default=None)


def set_user(email: str) -> contextvars.Token:
    return _current.set(email.strip().lower())


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> str:
    email = _current.get()
    if not email:
        raise RuntimeError("no user bound: data access outside a request or tenant.as_user()")
    return email


def partition() -> str:
    """The data partition db calls touch: shares/{id} when one is bound, else the user's own."""
    return _partition.get() or f"users/{current()}"


def set_partition(path: str | None) -> contextvars.Token:
    return _partition.set(path)


def reset_partition(token: contextvars.Token) -> None:
    _partition.reset(token)


@contextlib.contextmanager
def as_user(email: str) -> Iterator[None]:
    """Bind a user and their own partition (a share bound outside is dropped, so a
    loop over users never touches a share by accident)."""
    token = set_user(email)
    part = set_partition(None)
    try:
        yield
    finally:
        reset_partition(part)
        reset(token)


@contextlib.contextmanager
def as_partition(path: str) -> Iterator[None]:
    token = set_partition(path)
    try:
        yield
    finally:
        reset_partition(token)
