"""Whose data the current request works on.

Set once per request by app.auth.bind_user, or around background work with as_user().
Every Firestore path and blob key is derived from current(); with nobody bound it
raises, so a forgotten binding fails loudly instead of touching the wrong account."""
from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_user", default=None)


def set_user(email: str) -> contextvars.Token:
    return _current.set(email.strip().lower())


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> str:
    email = _current.get()
    if not email:
        raise RuntimeError("no user bound: data access outside a request or tenant.as_user()")
    return email


@contextlib.contextmanager
def as_user(email: str) -> Iterator[None]:
    token = set_user(email)
    try:
        yield
    finally:
        reset(token)
