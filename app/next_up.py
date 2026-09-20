"""Ranking for the "Next up" view: what to work on next.

Pure functions over already-loaded todos, so the ordering is easy to test.

A todo is worth working on when it is open and has nothing open beneath it (a
parent is finished by finishing its children). Candidates are ranked by:

1. effective due date: the earlier of the todo's own due date and its nearest
   due ancestor's, so subtasks of a parent due Friday count as due Friday.
   Due dates carry an optional time: within a day the earlier time comes
   first, and a date-only (all-day) due counts as the end of that day
2. its own due date (a subtask with its own earlier date beats undated siblings)
3. list position: root order, then each level's order_idx, top to bottom

Todos with no date anywhere go last, in list order.

The list is `limit` long, but never cuts off a todo whose effective due date is
`today` or earlier (when `today` is given): all of those are shown, and if they
number fewer than `limit` the next most urgent fill it up.

Blocking: a todo waits on the open todos in its blocked_by (and its ancestors').
After ranking, each blocker is pulled up to sit just above what it blocks, so
the blocked todo is never demoted for it. A blocker with open subtasks brings
all its open leaves along. Done or deleted blockers don't count.
"""
from __future__ import annotations

import datetime

from app import models

DEFAULT_LIMIT = 10
_NO_DATE = datetime.datetime.max


def _due(todo: models.Todo) -> datetime.datetime | None:
    """The moment a todo is due. A date-only due is stored as midnight and means
    all-day, so it sorts as the end of that day (after any timed due that day)."""
    due = todo.due_date
    if due is None:
        return None
    if due.time() == datetime.time(0, 0):
        due = due.replace(hour=23, minute=59, second=59)
    # _NO_DATE is naive, so an offset-aware due is compared as UTC wall time.
    if due.tzinfo is not None:
        due = due.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return due


def rank_next_up(roots: list[models.Todo], by_id: dict[str, models.Todo],
                 limit: int = DEFAULT_LIMIT,
                 today: datetime.date | None = None) -> list[dict]:
    candidates: list[tuple] = []

    def open_children(todo: models.Todo) -> list[models.Todo]:
        kids = [by_id[str(cid)] for cid in todo.child_ids if str(cid) in by_id]
        kids = [k for k in kids if not k.done and not k.deleted]
        # Same ordering the client uses for a parent's children.
        return sorted(kids, key=lambda k: k.order_idx if k.order_idx is not None else 999999)

    def walk(todo: models.Todo, index_path: tuple[int, ...], titles: list[str],
             inherited: tuple[datetime.datetime, models.Todo] | None) -> None:
        own = _due(todo)
        best = inherited
        if own is not None and (best is None or own < best[0]):
            best = (own, todo)

        kids = open_children(todo)
        if not kids:
            source = best[1] if best else None
            candidates.append((
                best[0] if best else _NO_DATE,
                own or _NO_DATE,
                index_path,
                todo,
                titles,
                # A datetime, like due_date, so the client parses both the same way.
                source.due_date if source else None,
                "self" if source is todo else ("parent" if source else None),
            ))
            return
        for i, kid in enumerate(kids):
            walk(kid, index_path + (i,), titles + [todo.title], best)

    for i, root in enumerate(roots):
        if not root.done and not root.deleted:
            walk(root, (i,), [], None)

    candidates.sort(key=lambda c: (c[0], c[1], c[2]))

    def open_blockers(todo: models.Todo) -> list[models.Todo]:
        """Open todos this one waits on: its own blocked_by plus its ancestors'."""
        found: dict[str, models.Todo] = {}
        node, seen = todo, set()
        while node is not None and str(node.todo_id) not in seen:
            seen.add(str(node.todo_id))
            for bid in node.blocked_by:
                b = by_id.get(str(bid))
                if b is not None and not b.done and not b.deleted:
                    found.setdefault(str(b.todo_id), b)
            node = by_id.get(str(node.parent_id)) if node.parent_id else None
        return list(found.values())

    def under(todo: models.Todo, ancestor: models.Todo) -> bool:
        node, seen = todo, set()
        while node is not None and str(node.todo_id) not in seen:
            if node.todo_id == ancestor.todo_id:
                return True
            seen.add(str(node.todo_id))
            node = by_id.get(str(node.parent_id)) if node.parent_id else None
        return False

    placed: set[str] = set()
    visiting: set[str] = set()
    ordered: list[tuple] = []

    def place(cand: tuple) -> None:
        key = str(cand[3].todo_id)
        if key in placed or key in visiting:
            return
        visiting.add(key)
        blockers = open_blockers(cand[3])
        for other in candidates:  # rank order
            if other is not cand and any(under(other[3], b) for b in blockers):
                place(other)
        visiting.discard(key)
        placed.add(key)
        ordered.append(cand)

    for cand in candidates:
        place(cand)
    candidates = ordered

    if today is not None:
        due_now = [i for i, c in enumerate(candidates) if c[0].date() <= today]
        if due_now:
            limit = max(limit, due_now[-1] + 1)

    items = []
    for rank, (_, _, _, todo, titles, effective, source) in enumerate(candidates[:limit], start=1):
        items.append({
            "rank": rank,
            "todo_id": str(todo.todo_id),
            "title": todo.title,
            "due_date": todo.due_date,
            "effective_due": effective,
            "due_source": source,
            "parent_id": str(todo.parent_id) if todo.parent_id else None,
            "path": titles,
            "blocked_by": [b.title for b in open_blockers(todo)],
        })
    return items
