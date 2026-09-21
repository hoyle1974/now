"""Item types: what each type can do, read from app/types.json.

The same JSON generates web/types-data.js (scripts/gen_types.py), so the server
and the client can never disagree. Feature code asks `can(item, flag)`; it never
compares a type name. A missing or unknown type behaves as "todo".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SPEC: dict[str, dict[str, Any]] = json.loads(Path(__file__).with_name("types.json").read_text())
DEFAULT = "todo"
NAMES = tuple(_SPEC)


def caps(name: str | None) -> dict[str, Any]:
    return _SPEC.get(name or DEFAULT, _SPEC[DEFAULT])


def can_type(name: str | None, flag: str) -> bool:
    return bool(caps(name)[flag])


def can(item: Any, flag: str) -> bool:
    return can_type(getattr(item, "type", DEFAULT), flag)


def has_field_type(name: str | None, field: str) -> bool:
    return field in caps(name)["fields"]


def has_field(item: Any, field: str) -> bool:
    return has_field_type(getattr(item, "type", DEFAULT), field)
