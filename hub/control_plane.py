"""Control-plane prototypes for internal AI tasks (no provider calls)."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3

ROLES = frozenset({"ceo", "sales_manager", "production_manager", "qa_manager", "admin_manager", "worker"})
PERMISSIONS = {
    "ceo": {"plan", "assign", "review", "report"},
    "sales_manager": {"plan", "assign", "report"},
    "production_manager": {"plan", "assign", "review", "report"},
    "qa_manager": {"review", "report"},
    "admin_manager": {"report"},
    "worker": {"execute"},
}

def timestamp(dt=None):
    dt = dt or datetime.now(timezone.utc)
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise ValueError("timezone aware datetime required")
    return dt.astimezone(timezone.utc).isoformat()

class ControlPlane:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS task_links(
                    parent TEXT NOT NULL, child TEXT NOT NULL,
                    PRIMARY KEY(parent,child), CHECK(parent != child)
                );
                CREATE TABLE IF NOT EXISTS task_priority(
                    task_id TEXT PRIMARY KEY, priority INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_leases(
                    task_id TEXT PRIMARY KEY, worker TEXT NOT NULL,
                    expires TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_budgets(
                    project_id TEXT PRIMARY KEY, cap INTEGER NOT NULL, spent INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS assignment_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL, worker TEXT NOT NULL,
                    at TEXT NOT NULL
                );
            """)

    # 1. Role validation
    def allow(self, role, permission):
        return role in ROLES and permission in PERMISSIONS[role]

    # 2. Project budget reservation (integer minor units)
    def set_budget(self, project, cap):
        if not project or type(cap) is not int or cap < 0:
            raise ValueError("invalid project budget")
        with self.db:
            self.db.execute("INSERT INTO project_budgets(project_id,cap) VALUES (?,?) ON CONFLICT(project_id) DO UPDATE SET cap=excluded.cap WHERE spent<=excluded.cap", (project,cap))
        return self.budget(project)

    # 3. Atomic budget charge
    def charge(self, project, amount):
        if type(amount) is not int or amount < 0:
            raise ValueError("invalid charge")
        with self.db:
            updated=self.db.execute("UPDATE project_budgets SET spent=spent+? WHERE project_id=? AND spent+?<=cap", (amount,project,amount)).rowcount
            if not updated:
                raise PermissionError("budget unavailable or exceeded")
        return self.budget(project)

    # 4. Budget snapshot
    def budget(self, project):
        row=self.db.execute("SELECT cap,spent FROM project_budgets WHERE project_id=?", (project,)).fetchone()
        return dict(row) if row else None

    # 5. Dependency with cycle prevention
    def depend_on(self, task_id, prerequisite):
        self.store.get(task_id); self.store.get(prerequisite)
        if task_id == prerequisite:
            raise ValueError("self-dependency")
        def ancestors(tid, seen=None):
            seen=seen or set()
            for row in self.db.execute("SELECT parent FROM task_links WHERE child=?", (tid,)):
                parent=row["parent"]
                if parent not in seen:
                    seen.add(parent); ancestors(parent, seen)
            return seen
        # parent=prerequisite -> child=task_id. Reject if task_id is already an ancestor of prerequisite.
        if task_id in ancestors(prerequisite):
            raise ValueError("dependency cycle")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO task_links(parent,child) VALUES (?,?)", (prerequisite,task_id))

    # 6. Priority, higher means sooner
    def prioritize(self, task_id, priority):
        self.store.get(task_id)
        if type(priority) is not int or not -100 <= priority <= 100:
            raise ValueError("priority -100..100")
        with self.db:
            self.db.execute("INSERT INTO task_priority(task_id,priority) VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET priority=excluded.priority", (task_id,priority))

    # 7. Dependency-aware ready queue
    def ready(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid limit")
        rows=self.db.execute("""
          SELECT t.task_id,t.title,t.department,COALESCE(p.priority,0) AS priority
          FROM tasks t LEFT JOIN task_priority p ON p.task_id=t.task_id
          WHERE t.state='queued' AND NOT EXISTS (
            SELECT 1 FROM task_links l JOIN tasks parent ON parent.task_id=l.parent
            WHERE l.child=t.task_id AND parent.state!='completed'
          )
          AND NOT EXISTS (SELECT 1 FROM worker_leases w WHERE w.task_id=t.task_id)
          ORDER BY priority DESC,t.created_at,t.task_id LIMIT ?
        """,(limit,)).fetchall()
        return [dict(x) for x in rows]

    # 8. Exclusive lease for internal task
    def claim(self, task_id, worker, *, at=None, ttl_seconds=120):
        if not worker or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("invalid worker or ttl")
        self.store.get(task_id)
        at=at or datetime.now(timezone.utc)
        expires=timestamp(at+timedelta(seconds=ttl_seconds))
        with self.db:
            self.db.execute("DELETE FROM worker_leases WHERE expires<=?",(timestamp(at),))
            row=self.db.execute("""
                INSERT INTO worker_leases(task_id,worker,expires)
                SELECT t.task_id,?,? FROM tasks t WHERE t.task_id=? AND t.state='queued'
                AND NOT EXISTS (SELECT 1 FROM worker_leases l WHERE l.task_id=t.task_id)
                AND NOT EXISTS (SELECT 1 FROM task_links l JOIN tasks p ON p.task_id=l.parent
                  WHERE l.child=t.task_id AND p.state!='completed')
                ON CONFLICT(task_id) DO NOTHING
            """,(worker,expires,task_id)).rowcount
            if not row:
                return False
            self.db.execute("INSERT INTO assignment_log(task_id,worker,at) VALUES (?,?,?)",(task_id,worker,timestamp(at)))
        return True

    # 9. Heartbeat
    def heartbeat(self, task_id, worker, *, at=None, ttl_seconds=120):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("invalid ttl")
        at=at or datetime.now(timezone.utc)
        with self.db:
            changed=self.db.execute("UPDATE worker_leases SET expires=? WHERE task_id=? AND worker=? AND expires>?",
                       (timestamp(at+timedelta(seconds=ttl_seconds)),task_id,worker,timestamp(at))).rowcount
        return bool(changed)

    # 10. Explicit release and stale-lease inspection (no auto replay)
    def release(self, task_id, worker):
        with self.db:
            return bool(self.db.execute("DELETE FROM worker_leases WHERE task_id=? AND worker=?", (task_id,worker)).rowcount)

    def expired_leases(self, *, at=None):
        return [dict(r) for r in self.db.execute("SELECT * FROM worker_leases WHERE expires<=?",(timestamp(at),))]

    def dashboard(self, project_id=None):
        tasks=self.store.list_tasks(project_id)
        counts={}
        for t in tasks:
            counts[t["state"]]=counts.get(t["state"],0)+1
        return {"total":len(tasks),"states":counts,
                "waiting_approval":counts.get("awaiting_approval",0),
                "blocked":counts.get("blocked",0)}
