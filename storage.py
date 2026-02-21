import json
import os
import uuid
from datetime import datetime

STORAGE_FILE = "tasks.json"

def load_tasks() -> list:
    if not os.path.exists(STORAGE_FILE):
        return []
    with open(STORAGE_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return []
        return json.loads(content)

def save_tasks(tasks: list):
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

def add_tasks(tasks: list, new_tasks: list) -> list:
    """Add new tasks to the list, return only the newly added ones."""
    added = []
    for t in new_tasks:
        task = {
            "id": str(uuid.uuid4())[:8],
            "name": t.get("name", "Tugas tanpa nama"),
            "description": t.get("description", ""),
            "deadline": t.get("deadline"),
            "links": [
                l if isinstance(l, dict) else {"label": "Link", "url": l}
                for l in t.get("links", [])
            ],  # support multiple named links
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        tasks.append(task)
        added.append(task)
    return added

def delete_task(tasks: list, task_id: str) -> bool:
    for i, t in enumerate(tasks):
        if t["id"] == task_id:
            tasks.pop(i)
            return True
    return False

def get_all_tasks() -> list:
    return load_tasks()

def update_task(tasks: list, task_id: str, fields: dict) -> bool:
    """Update fields tertentu dari sebuah task. Returns True jika berhasil."""
    for task in tasks:
        if task["id"] == task_id:
            task.update(fields)
            return True
    return False