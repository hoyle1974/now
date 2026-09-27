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

from app import auth, db, models, tenant

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


# ---- what a member sees -----------------------------------------------------------

def ensure_mounts(email: str) -> list[dict]:
    """Give the person a mount (at the end of their top level) for every live share they
    can see and have none for, removed ones included: removing is a choice to keep. Covers
    new shares and people added to the deployment later. Returns [{id, title, owner}] of
    the new ones that aren't their own, for the client to announce."""
    if not auth.sharing_enabled():
        return []
    have = {m["todo_id"] for m in mounts(email)}
    new: list[dict] = []
    for share in active_shares():
        if share.id in have or not is_member(share, email):
            continue
        with tenant.as_partition(share.partition()):
            root = db.get_todo(models.TodoId(share.id))
        if root is None:
            continue
        mount = models.Todo(todo_id=models.TodoId(share.id), title="", type="mount")
        with tenant.as_user(email):
            db.run_atomic(None, lambda m=mount: (db.create_todo(m), (200, None))[-1])
        if share.owner != email:
            new.append({"id": share.id, "title": root.title, "owner": share.owner})
    return new


def _visible(share: Share | None, email: str) -> bool:
    return share is not None and share.state == "active" and is_member(share, email)


def _detach(roots: list[models.Todo], by_id: dict[str, models.Todo], node: models.Todo) -> None:
    by_id.pop(str(node.todo_id), None)
    if node.parent_id is None:
        roots[:] = [r for r in roots if r.todo_id != node.todo_id]
    else:
        parent = by_id.get(str(node.parent_id))
        if parent is not None:
            parent.child_ids = [c for c in parent.child_ids if c != node.todo_id]


def splice_tree(email: str, roots: list[models.Todo], by_id: dict[str, models.Todo]) -> dict[str, int]:
    """Replace each of the person's mounts, in place, with the share's tree: the root takes
    the mount's position, every node is tagged `share`, `collapsed` comes from their view
    state. Mounts they can't see (sharing off, unshared, not a member, root deleted) are
    left out; a mount whose share no longer exists is deleted. Returns the share revs
    seen ({"shares/<id>": rev})."""
    seen: dict[str, int] = {}
    enabled = auth.sharing_enabled()
    for mount in [t for t in by_id.values() if t.type == "mount"]:
        share = get(str(mount.todo_id)) if enabled else None
        if enabled and share is None:
            db.user_ref(email).collection("todos").document(str(mount.todo_id)).delete()
        if not _visible(share, email):
            _detach(roots, by_id, mount)
            continue
        with tenant.as_partition(share.partition()):
            rev = db.get_rev()
            _, share_by_id = db.get_tree(rev)
        root = share_by_id.get(share.id)
        if root is None:  # the owner deleted it: hidden until restored
            _detach(roots, by_id, mount)
            continue
        seen[share.partition()] = rev
        tag = models.ShareTag(id=share.id, mode=share.mode, owner=share.owner)
        collapsed = get_view_state(email, share.id)
        for node in share_by_id.values():
            node.share = tag
            node.collapsed = str(node.todo_id) in collapsed
        root.share_root = True
        root.parent_id, root.order_idx = mount.parent_id, mount.order_idx
        by_id.update(share_by_id)
        if mount.parent_id is None:
            roots[:] = [root if r.todo_id == mount.todo_id else r for r in roots]
    return seen


def revs(email: str, own_rev: int) -> dict[str, int]:
    """{partition: rev} for everything the person sees: their own list, the share list
    ("shares") and each share they have mounted. The mount list is cached per own rev
    (adding, removing or moving a mount bumps it)."""
    out = {f"users/{email}": own_rev}
    if not auth.sharing_enabled():
        return out
    out[SHARES] = meta_rev()
    from app.db_firestore import _state
    cached = _state.mount_cache.get(email)
    if cached is None or cached[0] != own_rev:
        cached = (own_rev, mounted_share_ids(email))
        _state.mount_cache[email] = cached
    for share_id in cached[1]:
        share = get(share_id)
        if _visible(share, email):
            with tenant.as_partition(share.partition()):
                out[share.partition()] = db.get_rev()
    return out


def trash_sources(email: str) -> list[Share]:
    """Shares whose trash the person sees: mounted, live, and they may edit."""
    out = []
    for share_id in mounted_share_ids(email):
        share = get(share_id)
        if _visible(share, email) and can_write(share, email):
            out.append(share)
    return out


def visible_mounted(email: str) -> list[Share]:
    return [s for s in (get(i) for i in mounted_share_ids(email)) if _visible(s, email)]


# ---- cleanup ----------------------------------------------------------------------

def _drop_partition(share_id: str) -> None:
    ref = db.get_conn().collection(SHARES).document(share_id)
    for sub in ref.collections():
        for doc in sub.stream():
            doc.reference.delete()
    ref.delete()


_last_sweep: list[float] = []


def sweep_daily() -> int:
    """sweep() at most once a day per process (it streams every share doc)."""
    import time
    if _last_sweep and time.monotonic() - _last_sweep[0] < 24 * 3600:
        return 0
    _last_sweep[:] = [time.monotonic()]
    return sweep()


def sweep(now: datetime.datetime | None = None) -> int:
    """Delete unshared tombstones older than TOMBSTONE_DAYS (their txn_log with them) and end
    shares whose root is gone (archived). Returns how many shares were removed. Mounts that
    point at a removed share are deleted when their owner next loads the tree."""
    now = now or _now()
    removed = 0
    for snap in db.get_conn().collection(SHARES).stream():
        data = snap.to_dict() or {}
        state, updated = data.get("state"), data.get("updated_at")
        if state == "unshared" and updated and now - updated > datetime.timedelta(days=TOMBSTONE_DAYS):
            _drop_partition(snap.id)
            removed += 1
        elif state == "active" and not snap.reference.collection("todos").document(snap.id).get().exists:
            _drop_partition(snap.id)
            bump_meta_rev()
            removed += 1
    return removed


def members_with_mount(share: Share) -> list[str]:
    """Everyone who has this share in their list (a live mount): who hears its reminders."""
    out = []
    for email in auth.allowed_emails():
        if not is_member(share, email):
            continue
        snap = db.user_ref(email).collection("todos").document(share.id).get()
        if snap.exists and not (snap.to_dict() or {}).get("deleted"):
            out.append(email)
    return out
