"""Mock-only tests for phases 4 and 5."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from hub.task_store import TaskStore
from hub.control_plane import ControlPlane
from hub.dispatcher import RateLimited, WorkResult
from hub.parallel import ParallelRunner
from hub.retry_planner import RetryPlanner
from hub.orchestrator import Orchestrator

T0 = datetime(2026, 11, 17, tzinfo=timezone.utc)

class Phase45Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.tmp.name) / "tasks.sqlite")
        self.control = ControlPlane(self.store)
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def add(self, department="production"):
        task = self.store.create("mock", "Internal work", department)["task_id"]
        self.store.transition(task, "screened", actor="test")
        self.store.transition(task, "queued", actor="test")
        return task
    def runner(self, work):
        return ParallelRunner(self.store, self.control,
                              workers={"mock": work},
                              department_workers={"production": "mock"})
    def test_parallel_outputs_require_review(self):
        ids = [self.add() for _ in range(4)]
        outcomes = self.runner(lambda payload: WorkResult("mock://" + payload["task_id"])).tick(max_workers=3)
        self.assertEqual(len(outcomes), 4)
        self.assertTrue(all(self.store.get(t)["state"] == "reviewing" for t in ids))
        self.assertEqual(self.runner(lambda _: None).tick(), [])
    def test_unknown_department_is_not_run(self):
        task = self.add("unmapped")
        self.assertEqual(self.runner(lambda _: WorkResult("mock://ok")).tick(), [])
        self.assertEqual(self.store.get(task)["state"], "queued")
    def test_rate_limit_retry_and_resume(self):
        task = self.add()
        calls = []
        def worker(payload):
            calls.append(payload["task_id"])
            if len(calls) == 1:
                raise RateLimited("mock 429")
            return WorkResult("mock://done")
        retry = RetryPlanner(self.store, base_delay_seconds=10, cap_seconds=100)
        orchestrator = Orchestrator(retry, self.runner(worker))
        first = orchestrator.tick(at=T0)
        self.assertEqual(len(first["scheduled"]), 1)
        self.assertEqual(self.store.get(task)["state"], "retry_scheduled")
        self.assertEqual(orchestrator.tick(at=T0 + timedelta(seconds=9))["executed"], [])
        result = orchestrator.tick(at=T0 + timedelta(seconds=11))
        self.assertEqual(result["requeued"], [task])
        self.assertEqual(self.store.get(task)["state"], "reviewing")
        self.assertEqual(len(calls), 2)
    def test_invalid_worker_output_fails(self):
        task = self.add()
        self.runner(lambda _: None).tick()
        self.assertEqual(self.store.get(task)["state"], "failed")
    def test_parallel_limits(self):
        with self.assertRaises(ValueError):
            self.runner(lambda _: None).tick(max_workers=0)
        with self.assertRaises(ValueError):
            Orchestrator(RetryPlanner(self.store), self.runner(lambda _: None)).tick(max_tasks=101)
if __name__ == "__main__":
    unittest.main()
