"""Bounded internal-only queue runner.

No threads or long-running loop here. The caller schedules explicit ticks.
No outbound actions, approvals, or live provider connections are supported.
"""
from .dispatcher import Dispatcher

class QueueRunner:
    def __init__(self, store, dispatcher: Dispatcher, *, worker_by_department):
        self.store = store
        self.dispatcher = dispatcher
        self.worker_by_department = dict(worker_by_department)

    def tick(self, *, max_tasks=5):
        if not isinstance(max_tasks, int) or not 1 <= max_tasks <= 100:
            raise ValueError("max_tasks must be 1..100")
        processed = []
        for task in self.store.list_tasks():
            if len(processed) >= max_tasks:
                break
            if task["state"] != "queued":
                continue
            worker = self.worker_by_department.get(task["department"])
            if worker is None or worker not in self.dispatcher.workers:
                continue
            outcome = self.dispatcher.run(task["task_id"], worker, action="internal",
                                          payload={"task_id": task["task_id"], "title": task["title"]})
            processed.append({"task_id": task["task_id"], "state": outcome["state"],
                              "executor": worker})
        return processed
