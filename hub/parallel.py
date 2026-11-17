"""Bounded parallel execution of trusted, internal-only mock worker functions.

State mutations happen on the caller thread: sqlite3 connections are never shared
with executor threads. This is a prototype, not a process-safe distributed queue.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

@dataclass(frozen=True)
class ParallelOutcome:
    task_id: str
    state: str

class ParallelRunner:
    def __init__(self, store, control, *, workers, department_workers):
        self.store = store
        self.control = control
        self.workers = dict(workers)
        self.department_workers = dict(department_workers)

    def tick(self, *, max_workers=2, max_tasks=10):
        if type(max_workers) is not int or not 1 <= max_workers <= 8:
            raise ValueError("max_workers must be in 1..8")
        if type(max_tasks) is not int or not 1 <= max_tasks <= 100:
            raise ValueError("max_tasks must be in 1..100")
        from .dispatcher import WorkResult, RateLimited
        submitted = []
        for task in self.control.ready(limit=max_tasks):
            worker_name = self.department_workers.get(task["department"])
            if worker_name not in self.workers:
                continue
            if not self.control.claim(task["task_id"], worker_name):
                continue
            try:
                self.store.transition(task["task_id"], "running",
                                      actor="parallel_runner", executor=worker_name)
            except Exception:
                self.control.release(task["task_id"], worker_name)
                raise
            submitted.append((task, worker_name))
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(self.workers[worker], {"task_id": task["task_id"], "title": task["title"]}):
                (task["task_id"], worker)
                for task, worker in submitted
            }
            for future in as_completed(future_map):
                task_id, worker_name = future_map[future]
                try:
                    output = future.result()
                    if not isinstance(output, WorkResult) or not output.output_ref:
                        raise ValueError("worker must return WorkResult with output_ref")
                except RateLimited as err:
                    self.store.transition(task_id, "rate_limited", actor=worker_name, note=str(err))
                except Exception as err:
                    self.store.transition(task_id, "failed", actor=worker_name,
                                          note=f"{type(err).__name__}: {err}")
                else:
                    self.store.transition(task_id, "reviewing", actor=worker_name,
                                          output_ref=output.output_ref, note=output.summary)
                finally:
                    self.control.release(task_id, worker_name)
                results.append(ParallelOutcome(task_id, self.store.get(task_id)["state"]))
        return results
