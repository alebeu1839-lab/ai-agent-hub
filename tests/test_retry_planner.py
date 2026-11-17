import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from hub.task_store import TaskStore
from hub.retry_planner import RetryPlanner

T0 = datetime(2026, 11, 17, tzinfo=timezone.utc)

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.db"
        self.store = TaskStore(self.path)
        self.planner = RetryPlanner(self.store, base_delay_seconds=10,
                                    cap_seconds=100, max_attempts=2)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def limited_task(self):
        task = self.store.create("test", "mock", "production")["task_id"]
        for state in ("screened", "queued", "running", "rate_limited"):
            self.store.transition(task, state, actor="test")
        return task

    def test_persist_due_recovery(self):
        task = self.limited_task()
        result = self.planner.schedule(task, error="429", at=T0)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(self.planner.requeue_due(at=T0 + timedelta(seconds=9)), [])
        self.store.close()
        self.store = TaskStore(self.path)
        self.planner = RetryPlanner(self.store, base_delay_seconds=10,
                                    cap_seconds=100, max_attempts=2)
        self.assertEqual(self.planner.requeue_due(at=T0 + timedelta(seconds=11)), [task])
        self.assertEqual(self.store.get(task)["state"], "queued")

    def test_retry_budget_blocks(self):
        task = self.limited_task()
        self.planner.schedule(task, error="429", at=T0)
        self.planner.requeue_due(at=T0 + timedelta(seconds=10))
        self.store.transition(task, "running", actor="test")
        self.store.transition(task, "rate_limited", actor="test")
        result = self.planner.schedule(task, error="429", at=T0 + timedelta(seconds=10))
        self.assertEqual(result["attempts"], 2)
        self.planner.requeue_due(at=T0 + timedelta(seconds=30))
        self.store.transition(task, "running", actor="test")
        self.store.transition(task, "rate_limited", actor="test")
        self.assertEqual(self.planner.schedule(task, error="429")["state"], "blocked")

    def test_retry_after_and_wrong_state(self):
        task = self.limited_task()
        result = self.planner.schedule(task, error="provider", at=T0, retry_after_seconds=60)
        self.assertEqual(result["next_retry_at"], (T0 + timedelta(seconds=60)).isoformat())
        with self.assertRaises(ValueError):
            self.planner.schedule(task, error="again")
        self.assertEqual(self.planner.requeue_due(at=T0 + timedelta(seconds=59)), [])

    def test_reject_naive_datetime(self):
        task = self.limited_task()
        with self.assertRaises(ValueError):
            self.planner.schedule(task, error="429", at=datetime(2026, 11, 17))

if __name__ == "__main__":
    unittest.main()
