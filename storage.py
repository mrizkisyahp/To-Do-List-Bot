import os
import json
import uuid
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Buat tabel kalau belum ada."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    deadline TEXT,
                    links JSONB DEFAULT '[]',
                    reminded JSONB DEFAULT '[]',
                    created_at TEXT
                )
            """)
        conn.commit()

def load_tasks() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tasks ORDER BY deadline NULLS LAST")
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def save_tasks(tasks: list):
    """Tidak dipakai lagi — operasi langsung ke DB."""
    pass

def add_tasks(tasks: list, new_tasks: list) -> list:
    added = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for t in new_tasks:
                task = {
                    "id": str(uuid.uuid4())[:8],
                    "name": t.get("name", "Tugas tanpa nama"),
                    "description": t.get("description", ""),
                    "deadline": t.get("deadline"),
                    "links": [
                        l if isinstance(l, dict) else {"label": "Link", "url": l}
                        for l in t.get("links", [])
                    ],
                    "reminded": [],
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                cur.execute("""
                    INSERT INTO tasks (id, name, description, deadline, links, reminded, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    task["id"], task["name"], task["description"],
                    task["deadline"], json.dumps(task["links"]),
                    json.dumps(task["reminded"]), task["created_at"]
                ))
                added.append(task)
        conn.commit()
    return added

def delete_task(tasks: list, task_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted

def update_task(tasks: list, task_id: str, fields: dict) -> bool:
    if not fields:
        return False
    
    # Handle special JSON fields
    set_clauses = []
    values = []
    for key, val in fields.items():
        if key in ("links", "reminded"):
            set_clauses.append(f"{key} = %s")
            values.append(json.dumps(val))
        else:
            set_clauses.append(f"{key} = %s")
            values.append(val)
    
    values.append(task_id)
    query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = %s"
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
            updated = cur.rowcount > 0
        conn.commit()
    return updated

def get_all_tasks() -> list:
    return load_tasks()
