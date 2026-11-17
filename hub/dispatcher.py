"""Safe explicit worker dispatch; no real external AI connection."""
from dataclasses import dataclass
from typing import Callable

EXTERNAL_ACTIONS = frozenset({
    "send_email", "send_message", "apply_job", "accept_contract",
    "submit_delivery", "publish", "purchase", "change_billing",
    "delete_remote_data", "share_secret"
})

class ApprovalRequired(PermissionError):
    pass

class WorkerFailure(RuntimeError):
    pass

class RateLimited(WorkerFailure):
    pass

@dataclass(frozen=True)
class WorkResult:
    output_ref: str
    summary: str = ""

class Dispatcher:
    """Dispatch queued work to registered workers; hold outputs for QA.

    External actions are disabled entirely until a durable, authenticated,
    per-action approval ledger and safe outbound connector are implemented.
    """
    def __init__(self, store, *, workers: dict[str, Callable], approvals=None):
        self.store = store
        self.workers = dict(workers)
        self.approvals = set(approvals or ())

    def run(self, task_id: str, worker_name: str, *, action="internal", payload=None):
        task = self.store.get(task_id)
        if task["state"] != "queued":
            raise ValueError("task must be queued")
        if action in EXTERNAL_ACTIONS:
            self.store.transition(task_id, "awaiting_approval", actor="dispatcher",
                                  note=f"approval required: {action}")
            raise ApprovalRequired(f"approval required for {action}")
        if action not in EXTERNAL_ACTIONS and action != "internal":
            raise ValueError("unknown action: fail closed")
        if worker_name not in self.workers:
            raise ValueError("unknown worker")
        self.store.transition(task_id, "running", actor="dispatcher", executor=worker_name)
        try:
            result = self.workers[worker_name](payload)
            if not isinstance(result, WorkResult) or not result.output_ref:
                raise WorkerFailure("worker must return a nonempty output reference")
        except RateLimited as exc:
            self.store.transition(task_id, "rate_limited", actor=worker_name, note=str(exc))
            return self.store.get(task_id)
        except Exception as exc:
            self.store.transition(task_id, "failed", actor=worker_name,
                                  note=f"{type(exc).__name__}: {exc}")
            return self.store.get(task_id)
        self.store.transition(task_id, "reviewing", actor=worker_name,
                              output_ref=result.output_ref, note=result.summary)
        return self.store.get(task_id)

    def approve_review(self, task_id: str, *, reviewer: str):
        if self.store.get(task_id)["state"] != "reviewing":
            raise ValueError("task is not under review")
        return self.store.transition(task_id, "completed", actor=reviewer, note="QA approved")

    def request_revision(self, task_id: str, *, reviewer: str, reason: str):
        if not reason.strip():
            raise ValueError("revision reason required")
        return self.store.transition(task_id, "queued", actor=reviewer, note=reason)
