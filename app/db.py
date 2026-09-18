# sqlite3 connection handling and schema setup go here.
from __future__ import annotations
import sqlite3
import threading
from app import models
import uuid
import datetime

conn = None
# The connection is shared across every request (FastAPI runs sync path
# operations in a threadpool, and conn is opened with
# check_same_thread=False), so all access to it is serialized through
# this lock to prevent concurrent requests from interleaving statements
# on the same transaction.
_lock = threading.Lock()

def init(memory:bool = False):
    global conn

    teardown()

    if memory:
        print("sqlite3: memory")
        conn = sqlite3.connect(":memory:",check_same_thread=False )
    else:
        print("sqlite3: todo.db")
        conn = sqlite3.connect("todo.db",check_same_thread=False )

    conn.row_factory = sqlite3.Row

    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS TODO_ITEMS (
            todo_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            done INTEGER NOT NULL,
            create_date TEXT NOT NULL,
            due_date TEXT,
            order_idx INTEGER,
            parent_id TEXT REFERENCES TODO_ITEMS(todo_id) ON DELETE CASCADE,
            deleted INTEGER NOT NULL DEFAULT 0
        );
        """)

    # Migration: an existing todo.db predating the `deleted` column won't
    # get it from CREATE TABLE IF NOT EXISTS, so add it explicitly.
    cur.execute("PRAGMA table_info(TODO_ITEMS)")
    columns = [row["name"] for row in cur.fetchall()]
    if "deleted" not in columns:
        cur.execute("ALTER TABLE TODO_ITEMS ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")

    conn.commit()

def get_conn():
    global conn
    return conn

def teardown():
    global conn

    if conn is not None:
        conn.close()
    conn = None


def _create_todo(cur: sqlite3.Cursor, todo: models.Todo):
    cur.execute("""
        INSERT INTO TODO_ITEMS
            (todo_id, title, done, create_date, due_date, order_idx, parent_id)
        VALUES
            (?,?,?,?,?,?,?)
        """,(
        str(todo.todo_id),
        todo.title,
        todo.done,
        todo.create_date.isoformat(),
        None if todo.due_date is None else todo.due_date.isoformat(),
        todo.order_idx,
        None if todo.parent_id is None else str(todo.parent_id)))

def create_todo(todo:models.Todo):
    with _lock:
        cur = get_conn().cursor()
        _create_todo(cur, todo)
        get_conn().commit()

def delete_todo(todo_id: models.TodoId):
    with _lock:
        cur = get_conn().cursor()
        # Soft delete: mark the target row and its whole subtree as
        # deleted in one statement, rather than walking it level by
        # level in Python. The recursive CTE is seeded with the target
        # id itself (not just its children) since, unlike cascade_done,
        # there's no separate UPDATE for the root row here.
        cur.execute("""
            WITH RECURSIVE subtree(todo_id) AS (
                SELECT ?
                UNION ALL
                SELECT t.todo_id FROM TODO_ITEMS t
                JOIN subtree s ON t.parent_id = s.todo_id
            )
            UPDATE TODO_ITEMS SET deleted = 1
            WHERE todo_id IN (SELECT todo_id FROM subtree)
            """,(str(todo_id),))
        get_conn().commit()

def reorder_todo(todo_id: models.TodoId, direction: str):
    """Move a todo up or down within its siblings by swapping order_idx"""
    with _lock:
        cur = get_conn().cursor()
        cur.execute("BEGIN")
        try:
            # Get the current todo's parent and order_idx
            cur.execute("""
                SELECT parent_id, order_idx FROM TODO_ITEMS WHERE todo_id = ? AND deleted = 0
                """, (str(todo_id),))
            row = cur.fetchone()
            if row is None:
                raise Exception("Todo not found")

            parent_id, current_idx = row["parent_id"], row["order_idx"]

            # If this todo has no order_idx, assign it one based on siblings
            if current_idx is None:
                cur.execute("""
                    SELECT COALESCE(max(order_idx), -1) as m FROM TODO_ITEMS
                    WHERE parent_id = ? AND deleted = 0
                    """, (parent_id,))
                max_row = cur.fetchone()
                current_idx = max_row["m"] + 1
                cur.execute("""UPDATE TODO_ITEMS SET order_idx = ? WHERE todo_id = ?""",
                           (current_idx, str(todo_id)))

            if direction == "up":
                # Find the sibling with the highest order_idx less than current
                cur.execute("""
                    SELECT todo_id, order_idx FROM TODO_ITEMS
                    WHERE parent_id = ? AND order_idx < ? AND deleted = 0
                    ORDER BY order_idx DESC LIMIT 1
                    """, (parent_id, current_idx))
            else:  # down
                # Find the sibling with the lowest order_idx greater than current
                cur.execute("""
                    SELECT todo_id, order_idx FROM TODO_ITEMS
                    WHERE parent_id = ? AND order_idx > ? AND deleted = 0
                    ORDER BY order_idx ASC LIMIT 1
                    """, (parent_id, current_idx))

            swap_row = cur.fetchone()
            if swap_row is None:
                raise Exception("Cannot move in that direction")

            swap_idx = swap_row["order_idx"]

            # Swap the order_idx values
            cur.execute("""UPDATE TODO_ITEMS SET order_idx = ? WHERE todo_id = ?""",
                       (swap_idx, str(todo_id)))
            cur.execute("""UPDATE TODO_ITEMS SET order_idx = ? WHERE todo_id = ?""",
                       (current_idx, swap_row["todo_id"]))

            get_conn().commit()
        except Exception:
            get_conn().rollback()
            raise

def undelete_todo(todo_id: models.TodoId):
    """Restore a soft-deleted todo and its entire subtree"""
    with _lock:
        cur = get_conn().cursor()
        # Undelete the target row and its whole subtree in one statement,
        # mirroring the logic of delete_todo but marking deleted = 0.
        cur.execute("""
            WITH RECURSIVE subtree(todo_id) AS (
                SELECT ?
                UNION ALL
                SELECT t.todo_id FROM TODO_ITEMS t
                JOIN subtree s ON t.parent_id = s.todo_id
            )
            UPDATE TODO_ITEMS SET deleted = 0
            WHERE todo_id IN (SELECT todo_id FROM subtree)
            """,(str(todo_id),))
        get_conn().commit()

def update_todo(todo: models.Todo, cascade_done: bool = False):
    with _lock:
        cur = get_conn().cursor()
        cur.execute("BEGIN")
        try:
            cur.execute("""
                UPDATE TODO_ITEMS
                SET title = ?, done = ?, due_date = ?, deleted = ? WHERE todo_id = ?
                """,(
                todo.title,
                todo.done,
                None if todo.due_date is None else todo.due_date.isoformat(),
                todo.deleted,
                str(todo.todo_id)))

            if cascade_done:
                # Mark the whole subtree done/not-done in one statement
                # rather than walking it level by level in Python.
                cur.execute("""
                    WITH RECURSIVE descendants(todo_id) AS (
                        SELECT todo_id FROM TODO_ITEMS WHERE parent_id = ?
                        UNION ALL
                        SELECT t.todo_id FROM TODO_ITEMS t
                        JOIN descendants d ON t.parent_id = d.todo_id
                    )
                    UPDATE TODO_ITEMS SET done = ?
                    WHERE todo_id IN (SELECT todo_id FROM descendants)
                    """, (str(todo.todo_id), todo.done))

            get_conn().commit()
        except Exception:
            get_conn().rollback()
            raise

def update_parent_id(todo:models.Todo, parent_id: models.TodoId | None) -> models.Todo | None:

    with _lock:
        cur = get_conn().cursor()

        try:
            cur.execute("""
                UPDATE TODO_ITEMS
                SET parent_id = ? WHERE todo_id = ?
                """,(None if parent_id is None else str(parent_id), str(todo.todo_id)))
            rowcount = cur.rowcount
            if rowcount == 0:
                get_conn().rollback()
                return None
            get_conn().commit()
            todo.parent_id = parent_id
            return todo
        except sqlite3.IntegrityError:
            get_conn().rollback()
            return None

def _populate_children(cur: sqlite3.Cursor, todo: models.Todo):
    child_ids = []
    cur.execute("""
        select todo_id from TODO_ITEMS where parent_id = ? AND deleted = 0
        """, (str(todo.todo_id),))
    rows = cur.fetchall()
    for row in rows:
        child_id = uuid.UUID(row["todo_id"])
        child_ids.append(models.TodoId(child_id))
    todo.child_ids = child_ids


def get_root_todos() -> list[models.Todo]:
    with _lock:
        cur = get_conn().cursor()
        cur.execute("""
            select todo_id, title, done, create_date, due_date, order_idx, parent_id from TODO_ITEMS where parent_id is null AND deleted = 0
            """)
        rows = cur.fetchall()

        todos = []
        for row in rows:
            todo = models.Todo(
                todo_id=models.TodoId(uuid.UUID(row["todo_id"])),
                title = row["title"],
                done = True if row["done"] == 1 else False,
                create_date =  datetime.datetime.fromisoformat(row["create_date"]),
                due_date =  None if row["due_date"] is None else datetime.datetime.fromisoformat(row["due_date"]),
                order_idx = row["order_idx"],
                parent_id = models.TodoId(uuid.UUID(row["parent_id"])) if row["parent_id"] is not None else None
            )
            _populate_children(cur, todo)
            todos.append(todo)

        return todos

def get_todo(todo_id: models.TodoId) -> models.Todo | None:
    with _lock:
        cur = get_conn().cursor()
        cur.execute("""
            select todo_id, title, done, create_date,due_date,order_idx, parent_id, deleted from TODO_ITEMS where todo_id = ? AND deleted = 0
            """, (str(todo_id),))
        row = cur.fetchone()
        if row is None:
            return None

        todo = models.Todo(
            todo_id=models.TodoId(uuid.UUID(row["todo_id"])),
            title = row["title"],
            done = True if row["done"] == 1 else False,
            create_date =  datetime.datetime.fromisoformat(row["create_date"]),
            due_date =  None if row["due_date"] is None else datetime.datetime.fromisoformat(row["due_date"]),
            order_idx = row["order_idx"],
            parent_id = models.TodoId(uuid.UUID(row["parent_id"])) if row["parent_id"] is not None else None,
            deleted = True if row["deleted"] == 1 else False
        )
        _populate_children(cur, todo)

        return todo

def get_deleted_todo(todo_id: models.TodoId) -> models.Todo | None:
    """Get a todo regardless of deleted status (for undo operations)"""
    with _lock:
        cur = get_conn().cursor()
        cur.execute("""
            select todo_id, title, done, create_date,due_date,order_idx, parent_id, deleted from TODO_ITEMS where todo_id = ?
            """, (str(todo_id),))
        row = cur.fetchone()
        if row is None:
            return None

        todo = models.Todo(
            todo_id=models.TodoId(uuid.UUID(row["todo_id"])),
            title = row["title"],
            done = True if row["done"] == 1 else False,
            create_date =  datetime.datetime.fromisoformat(row["create_date"]),
            due_date =  None if row["due_date"] is None else datetime.datetime.fromisoformat(row["due_date"]),
            order_idx = row["order_idx"],
            parent_id = models.TodoId(uuid.UUID(row["parent_id"])) if row["parent_id"] is not None else None,
            deleted = True if row["deleted"] == 1 else False
        )
        _populate_children(cur, todo)

        return todo

def split_into_children(todo: models.Todo, descriptions: list[str], due_date = None) -> models.Todo:
    with _lock:
        cur = get_conn().cursor()
        cur.execute("BEGIN")
        # Exclude soft-deleted children so their order_idx doesn't push new
        # siblings' indices higher than necessary among currently-visible ones.
        cur.execute("""select COALESCE(max(order_idx), -1) as m from TODO_ITEMS where parent_id = ? AND deleted = 0""", (str(todo.todo_id),))
        row = cur.fetchone()
        if row is None:
            raise Exception(f"unexpected result {row}")

        next_order = row["m"] + 1

        try:
            for description in descriptions:
                child_todo = models.Todo(title = description, parent_id = todo.todo_id, order_idx = next_order)
                if due_date:
                    child_todo.due_date = due_date
                _create_todo(cur, child_todo)
                next_order+=1

            _populate_children(cur, todo)
            get_conn().commit()
        except Exception:
            get_conn().rollback()
            raise

        return todo

