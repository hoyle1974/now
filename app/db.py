# sqlite3 connection handling and schema setup go here.
from __future__ import annotations 
import sqlite3
from app import models
import uuid
import datetime

conn = None

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
            parent_id TEXT REFERENCES TODO_ITEMS(todo_id) ON DELETE CASCADE
        );
        """)
    conn.commit()

def getConn():
    global conn
    return conn

def teardown():
    global conn

    if conn is not None:
        conn.close()
    conn = None


def _createTODO(cur: sqlite3.Cursor, todo: models.TODO):
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

def createTODO(todo:models.TODO):
    cur = getConn().cursor()
    _createTODO(cur, todo)
    getConn().commit()

def deleteTODO(todo_id: models.GenericId):
    cur = getConn().cursor()
    cur.execute("""
        DELETE FROM TODO_ITEMS where todo_id = ?
        """,(str(todo_id),))
    getConn().commit()

def updateTODO(todo:models.TODO):
    cur = getConn().cursor()
    cur.execute("""
        UPDATE TODO_ITEMS
        SET title = ?, done = ? WHERE todo_id = ?
        """,(todo.title, todo.done, str(todo.todo_id)))
    getConn().commit()

def updateParentId(todo:models.TODO, parent_id: models.GenericId | None) -> models.TODO | None:

    cur = getConn().cursor()

    try:
        cur.execute("""
            UPDATE TODO_ITEMS
            SET parent_id = ? WHERE todo_id = ? 
            """,(None if parent_id is None else str(parent_id), str(todo.todo_id)))
        rowcount = cur.rowcount 
        if rowcount == 0:
            return None
        getConn().commit()
        todo.parent_id = parent_id
        return todo
    except sqlite3.IntegrityError:
        return None

def _populateChildren(cur: sqlite3.Cursor, todo: models.TODO):
    child_ids = []
    cur.execute("""
        select todo_id from TODO_ITEMS where parent_id = ?
        """, (str(todo.todo_id),))
    rows = cur.fetchall()
    for row in rows:
        child_id = uuid.UUID(row["todo_id"])
        child_ids.append(models.GenericId(child_id))
    todo.child_ids = child_ids


def getRootTasks() -> list[models.TODO]:
    cur = getConn().cursor()
    cur.execute("""
        select todo_id, title, done, create_date, due_date, order_idx, parent_id from TODO_ITEMS where parent_id is null 
        """)
    rows = cur.fetchall()

    todos = []
    for row in rows:
        todo = models.TODO(
            todo_id=models.GenericId(uuid.UUID(row["todo_id"])),
            title = row["title"], 
            done = True if row["done"] == 1 else False, 
            create_date =  datetime.datetime.fromisoformat(row["create_date"]), 
            due_date =  None if row["due_date"] is None else datetime.datetime.fromisoformat(row["due_date"]), 
            order_idx = row["order_idx"],
            parent_id = models.GenericId(uuid.UUID(row["parent_id"])) if row["parent_id"] is not None else None
        )
        _populateChildren(cur, todo)
        todos.append(todo)

    return todos
   
def getTODO(todo_id: models.GenericId) -> models.TODO | None:
    cur = getConn().cursor()
    cur.execute("""
        select todo_id, title, done, create_date,due_date,order_idx, parent_id from TODO_ITEMS where todo_id = ? 
        """, (str(todo_id),))
    row = cur.fetchone()
    if row is None:
        return None

    todo = models.TODO(
        todo_id=models.GenericId(uuid.UUID(row["todo_id"])),
        title = row["title"], 
        done = True if row["done"] == 1 else False, 
        create_date =  datetime.datetime.fromisoformat(row["create_date"]), 
        due_date =  None if row["due_date"] is None else datetime.datetime.fromisoformat(row["due_date"]), 
        order_idx = row["order_idx"],
        parent_id = models.GenericId(uuid.UUID(row["parent_id"])) if row["parent_id"] is not None else None
    )
    _populateChildren(cur, todo)


    return todo
    
def splitIntoChildren(todo: models.TODO, descriptions: list[str]) -> models.TODO:
    cur = getConn().cursor()
    cur.execute("BEGIN")
    cur.execute("""select COALESCE(max(order_idx), -1) as m from TODO_ITEMS where parent_id = ?""", (str(todo.todo_id),))
    row = cur.fetchone()
    if row is None:
        raise Exception(f"unexpected result {row}")

    nextOrder = row["m"] + 1
   
    try: 
        for description in descriptions:
            childTODO = models.TODO(title = description, parent_id = todo.todo_id, order_idx = nextOrder)
            _createTODO(cur, childTODO)
            nextOrder+=1

        _populateChildren(cur, todo)
        getConn().commit()
    except Exception:  
        getConn().rollback()
        raise

    return todo
    
