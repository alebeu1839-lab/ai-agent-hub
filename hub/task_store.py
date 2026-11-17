"""Durable, stdlib-only task ledger for AI Agent Hub. No external actions."""
import sqlite3
import uuid
from datetime import datetime, timezone

TRANSITIONS = {
    "created": {"screened", "cancelled"},
    "screened": {"queued", "awaiting_approval", "cancelled"},
    "queued": {"running", "awaiting_approval", "blocked", "cancelled"},
    "running": {"reviewing", "rate_limited", "retry_scheduled", "failed", "blocked"},
    "reviewing": {"completed", "queued", "failed", "blocked"},
    "awaiting_approval": {"queued", "blocked", "cancelled"},
    "rate_limited": {"retry_scheduled", "blocked"},
    "retry_scheduled": {"queued", "blocked", "cancelled"},
    "blocked": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

def now():
    return datetime.now(timezone.utc).isoformat()

class TaskStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                department TEXT NOT NULL,
                state TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                executor TEXT,
                output_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                at TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT NOT NULL
            );
        """)

    def close(self):
        self.db.close()

    def get(self, task_id):
        row = self.db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return dict(row)

    def create(self, project_id, title, department, *, key=None, actor="system"):
        if not all(isinstance(v, str) and v.strip() for v in (project_id, title, department, actor)):
            raise ValueError("required fields must be nonempty text")
        if key is not None and (not isinstance(key, str) or not key.strip()):
            raise ValueError("key must be nonempty text")
        task_id, at = str(uuid.uuid4()), now()
        with self.db:
            if key:
                old = self.db.execute("SELECT * FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
                if old:
                    if (old["project_id"], old["title"], old["department"]) != (project_id, title, department):
                        raise ValueError("key already used by different task")
                    return dict(old)
            try:
                self.db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (task_id, project_id, title, department, "created", key, None, None, at, at))
            except sqlite3.IntegrityError:
                if not key:
                    raise
                old = self.db.execute("SELECT * FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
                if old and (old["project_id"], old["title"], old["department"]) == (project_id, title, department):
                    return dict(old)
                raise ValueError("idempotency key conflict")
            self.db.execute("INSERT INTO events(task_id,at,from_state,to_state,actor,note) VALUES (?,?,?,?,?,?)",
                            (task_id, at, None, "created", actor, "task created"))
        return self.get(task_id)

    def transition(self, task_id, target, *, actor, note="", executor=None, output_ref=None):
        if target not in TRANSITIONS or not isinstance(actor, str) or not actor.strip():
            raise ValueError("invalid state or actor")
        if executor is not None and (not isinstance(executor, str) or not executor.strip()):
            raise ValueError("invalid executor")
        if output_ref is not None and not isinstance(output_ref, str):
            raise ValueError("invalid output reference")
        with self.db:
            task = self.get(task_id)
            current = task["state"]
            if target not in TRANSITIONS[current]:
                raise ValueError(f"invalid transition: {current} -> {target}")
            if target == "completed" and not (output_ref or task["output_ref"]):
                raise ValueError("completed tasks require output reference")
            at = now()
            updated = self.db.execute(
                """UPDATE tasks SET state=?, executor=COALESCE(?,executor),
                output_ref=COALESCE(?,output_ref),updated_at=?
                WHERE task_id=? AND state=?""",
                (target, executor, output_ref, at, task_id, current),
            ).rowcount
            if updated != 1:
                raise RuntimeError("concurrent state change")
            self.db.execute("INSERT INTO events(task_id,at,from_state,to_state,actor,note) VALUES (?,?,?,?,?,?)",
                            (task_id, at, current, target, actor, note))
        return self.get(task_id)

    def history(self, task_id):
        self.get(task_id)
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM events WHERE task_id=? ORDER BY event_id", (task_id,)
        )]

    def list_tasks(self, project_id=None):
        if project_id is None:
            rows = self.db.execute("SELECT * FROM tasks ORDER BY created_at,task_id")
        else:
            rows = self.db.execute(
                "SELECT * FROM tasks WHERE project_id=? ORDER BY created_at,task_id", (project_id,)
            )
        return [dict(row) for row in rows]
