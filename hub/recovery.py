"""Fail-closed reconciliation of expired worker leases.

An expired heartbeat does NOT prove that a worker has stopped. Therefore, this
module only quarantines running tasks and never replays a pending operation.
"""
from datetime import datetime, timezone
from .control_plane import timestamp

class RecoveryController:
    def __init__(self, store, control):
        self.store = store
        self.control = control

    def inspect(self, *, at=None):
        """Return stale leases for operator inspection without any mutation."""
        rows = self.control.expired_leases(at=at)
        return [
            {"task_id": row["task_id"], "worker": row["worker"],
             "expires": row["expires"],
             "state": self.store.get(row["task_id"])["state"]}
            for row in rows
        ]

    def quarantine(self, *, at=None):
        """Mark stale running tasks blocked, retaining their leases.

        Keeping the lease prevents a second worker from claiming work that
        might still be running. An operator must verify actual worker shutdown
        before releasing the lease and manually requeuing the task.
        """
        blocked = []
        for stale in self.inspect(at=at):
            if stale["state"] != "running":
                continue
            self.store.transition(
                stale["task_id"], "blocked", actor="recovery_controller",
                note="heartbeat expired; worker termination unverified"
            )
            blocked.append(stale["task_id"])
        return blocked

    def release_verified(self, task_id, worker, *, operator, confirmed_stopped=False):
        """Release a stale lease only after explicit operator verification.

        No automatic task replay is performed here.
        """
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError("named operator required")
        if confirmed_stopped is not True:
            raise PermissionError("worker shutdown must be confirmed")
        if self.store.get(task_id)["state"] != "blocked":
            raise ValueError("task must be quarantined")
        lease = self.control.db.execute(
            "SELECT worker FROM worker_leases WHERE task_id=?", (task_id,)
        ).fetchone()
        if lease is None or lease["worker"] != worker:
            raise ValueError("lease owner mismatch")
        with self.store.db:
            released = self.control.release(task_id, worker)
            if not released:
                raise RuntimeError("lease changed")
            self.store.db.execute(
                "INSERT INTO events(task_id,at,from_state,to_state,actor,note) "
                "VALUES (?,?,?,?,?,?)",
                (task_id, timestamp(), "blocked", "blocked", operator,
                 "verified worker stopped; lease released; task remains blocked")
            )
        return True
