"""Sharing between the users of one deployment.

A shared subtree lives in its own partition, shares/{id} (same layout as a user's:
todos, txn_log, meta/rev, ...). The share doc itself (the partition's parent document)
holds who owns it, who may see it and whether members may edit. `id` is the shared
root's todo id. Every member places it in their own tree with a `mount` todo of the
same id (app/types.json); per-member collapse state lives in
users/{email}/view_state/{id}. See docs/okf/features/sharing.md.
"""
from __future__ import annotations

import contextvars
import datetime
from typing import Literal

from google.cloud import firestore  # type: ignore[attr-defined]
from pydantic import BaseModel, Field

from app import auth, db, tenant

SHARES = "shares"
META = ("shares_meta", "rev")      # bumped on share, unshare, mode change: the "shares" rev key
VIEW_STATE = "view_state"
VIEW_STATE_TTL = datetime.timedelta(days=90)
TOMBSTONE_DAYS = 30


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Share(BaseModel):
    id: str
    owner: str
    members: Literal["all"] | list[str] = "all"
    mode: Literal["ro", "rw"] = "rw"
    state: Literal["active", "migrating", "unshared"] = "active"
    returned_to: str | None = None
    created_at: datetime.datetime = Field(default_factory=_now)
    updated_at: datetime.datetime = Field(default_factory=_now)

    def partition(self) -> str:
        return f"{SHARES}/{self.id}"


def _ref(share_id: str):
    return db.get_conn().collection(SHARES).document(share_id)


def get(share_id: str) -> Share | None:
    snap = _ref(share_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    if "owner" not in data:
        return None  # only subcollections so far (a half-written share): not a share yet
    return Share(id=share_id, **{k: v for k, v in data.items() if k in Share.model_fields and k != "id"})


def put(share: Share) -> None:
    share.updated_at = _now()
    _ref(share.id).set(share.model_dump(exclude={"id"}))


def is_member(share: Share, email: str) -> bool:
    email = email.lower()
    if share.owner == email:
        return True
    if share.members == "all":
        return email in auth.allowed_emails()
    return email in share.members


def can_write(share: Share, email: str) -> bool:
    return share.owner == email.lower() or (is_member(share, email) and share.mode == "rw")


def _meta_ref():
    return db.get_conn().collection(META[0]).document(META[1])


def meta_rev() -> int:
    snap = _meta_ref().get()
    return (snap.to_dict() or {}).get("value", 0) if snap.exists else 0


def bump_meta_rev() -> None:
    _meta_ref().set({"value": firestore.Increment(1)}, merge=True)


def set_mode(share_id: str, mode: str) -> None:
    _ref(share_id).update({"mode": mode, "updated_at": _now()})
    bump_meta_rev()


def active_shares() -> list[Share]:
    out = []
    for snap in db.get_conn().collection(SHARES).where("state", "==", "active").stream():
        data = snap.to_dict() or {}
        out.append(Share(id=snap.id, **{k: v for k, v in data.items() if k in Share.model_fields and k != "id"}))
    return sorted(out, key=lambda s: s.id)


def mounts(email: str) -> list[dict]:
    """The person's mount docs (live and removed), as raw dicts."""
    query = db.user_ref(email).collection("todos").where("type", "==", "mount")
    return [snap.to_dict() for snap in query.stream()]


# ---- per-member view state -------------------------------------------------------

def _view_ref(email: str, share_id: str):
    return db.user_ref(email).collection(VIEW_STATE).document(share_id)


def get_view_state(email: str, share_id: str) -> set[str]:
    snap = _view_ref(email, share_id).get()
    return set((snap.to_dict() or {}).get("collapsed") or []) if snap.exists else set()


def set_collapsed(email: str, share_id: str, todo_id: str, collapsed: bool) -> None:
    """Expiry is refreshed on every write (Firestore TTL on expires_at, collection group
    view_state); losing it only shows shared nodes expanded again."""
    op = firestore.ArrayUnion([todo_id]) if collapsed else firestore.ArrayRemove([todo_id])
    _view_ref(email, share_id).set({"collapsed": op, "expires_at": _now() + VIEW_STATE_TTL}, merge=True)


# ---- the share bound to this request (auth.bind_partition) ------------------------

_bound: contextvars.ContextVar[Share | None] = contextvars.ContextVar("bound_share", default=None)


def bound() -> Share | None:
    """The share this request's X-Share named, when its partition is bound."""
    return _bound.get() if tenant.partition().startswith(f"{SHARES}/") else None


def bind(share: Share | None) -> contextvars.Token:
    return _bound.set(share)


# ---- where an item lives now ----------------------------------------------------

def mounted_share_ids(email: str) -> list[str]:
    """Shares the person has in their list (live mounts only)."""
    return sorted(m["todo_id"] for m in mounts(email) if not m.get("deleted"))


def locate(todo_id: str) -> str | None:
    """The partition an item the caller can reach lives in now, when it isn't in the bound
    one: their own partition, then each share they have mounted (a mount doc is not the
    item). For an edit a device queued before a share / unshare / move."""
    here, email = tenant.partition(), tenant.current()
    for part in [f"users/{email}", *(f"{SHARES}/{i}" for i in mounted_share_ids(email))]:
        if part == here:
            continue
        snap = db.partition_ref(part).collection("todos").document(todo_id).get()
        if snap.exists and (snap.to_dict() or {}).get("type") != "mount":
            return part
    return None


def check_partition_write(partition: str) -> Share | None:
    """May the caller write in this partition? Their own always; a share if it is active,
    they are a member and may edit. Raises the HTTP refusal otherwise; returns the share."""
    from fastapi import HTTPException
    email = tenant.current()
    if partition == f"users/{email}":
        return None
    if not partition.startswith(f"{SHARES}/"):
        raise HTTPException(403, "share revoked")
    share = get(partition.split("/", 1)[1])
    if share is None or share.state == "unshared" or not is_member(share, email):
        raise HTTPException(403, "share revoked")
    if share.state == "migrating":
        raise HTTPException(503, "migrating")
    if not can_write(share, email):
        raise HTTPException(403, "read only")
    return share


def bind_partition(partition: str, share: Share | None) -> None:
    """Rebind for the rest of this request (a request runs in its own context copy)."""
    tenant.set_partition(None if share is None else partition)
    bind(share)
