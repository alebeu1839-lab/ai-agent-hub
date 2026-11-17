"""Persistent retry planner. Only requeues; never invokes an external action."""
from datetime import datetime, timedelta, timezone

def utcnow():
    return datetime.now(timezone.utc)

def as_iso(value):
    if value.tzinfo is None:
        raise ValueError("timezone-aware UTC datetime required")
    return value.astimezone(timezone.utc).isoformat()

class RetryPlanner:
    def __init__(self, store, *, max_attempts=3, base_delay_seconds=30, cap_seconds=3600):
        if max_attempts < 1 or base_delay_seconds < 1 or cap_seconds < base_delay_seconds:
            raise ValueError("invalid retry policy")
        self.store = store
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.cap_seconds = cap_seconds
        self.store.db.execute("""
            CREATE TABLE IF NOT EXISTS retry_plan (
              task_id TEXT PRIMARY KEY,
              attempts INTEGER NOT NULL DEFAULT 0,
              next_retry_at TEXT NOT NULL,
              last_error TEXT NOT NULL,
              FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        """)
        self.store.db.commit()

    def schedule(self, task_id, *, error, at=None, retry_after_seconds=None):
        """Plan a retry for a task halted by the provider's rate limit.

        For safety, failed task execution from unknown errors is not retried
        automatically. A human/operator must inspect it first.
        """
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error required")
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be >= 0")
        current_time = at or utcnow()
        task = self.store.get(task_id)
        if task["state"] != "rate_limited":
            raise ValueError("only rate_limited tasks can be scheduled")
        row = self.store.db.execute(
            "SELECT attempts FROM retry_plan WHERE task_id=?", (task_id,)
        ).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        if attempts > self.max_attempts:
            self.store.transition(task_id, "blocked", actor="retry_planner",
                                  note="retry budget exhausted")
            return {"task_id": task_id, "state": "blocked", "attempts": attempts}
        delay = min(self.cap_seconds, self.base_delay_seconds * (2 ** (attempts - 1)))
        if retry_after_seconds is not None:
            delay = max(delay, retry_after_seconds)
        next_at = as_iso(current_time + timedelta(seconds=delay))
        with self.store.db:
            self.store.db.execute("""
                INSERT INTO retry_plan(task_id,attempts,next_retry_at,last_error)
                VALUES (?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                  attempts=excluded.attempts,
                  next_retry_at=excluded.next_retry_at,
                  last_error=excluded.last_error
            """, (task_id, attempts, next_at, error))
            self.store.transition(task_id, "retry_scheduled", actor="retry_planner",
                                  note=f"attempt {attempts}; due {next_at}: {error}")
        return {"task_id": task_id, "state": "retry_scheduled",
                "attempts": attempts, "next_retry_at": next_at}

    def requeue_due(self, *, at=None, limit=20):
        """Move due tasks to queued; caller must select an approved internal worker.

        Explicitly does not replay outbound requests or call a provider.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        at_string = as_iso(at or utcnow())
        due = self.store.db.execute("""
            SELECT r.task_id FROM retry_plan r JOIN tasks t ON t.task_id=r.task_id
            WHERE t.state='retry_scheduled' AND r.next_retry_at<=?
            ORDER BY r.next_retry_at LIMIT ?
        """, (at_string, limit)).fetchall()
        ready = []
        for row in due:
            task_id = row["task_id"]
            if self.store.get(task_id)["state"] != "retry_scheduled":
                continue
            self.store.transition(task_id, "queued", actor="retry_planner",
                                  note="retry due, requires safe internal dispatch")
            ready.append(task_id)
        return ready

    def inspect(self, task_id):
        row = self.store.db.execute(
            "SELECT * FROM retry_plan WHERE task_id=?", (task_id,)
        ).fetchone()
        return dict(row) if row else None
