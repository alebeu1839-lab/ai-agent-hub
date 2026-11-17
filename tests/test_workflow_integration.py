"""Integration tests for internal workflow; mocks only, no external services."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from hub.task_store import TaskStore
from hub.dispatcher import Dispatcher, RateLimited, WorkResult
from hub.queue_runner import QueueRunner
from hub.retry_planner import RetryPlanner

T0 = datetime(2026, 11, 17, tzinfo=timezone.utc)

class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.tmp.name) / "work.db")
        self.retry = RetryPlanner(self.store, base_delay_seconds=10, cap_seconds=100)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_rate_limit_recovery_to_review(self):
        task = self.store.create("demo", "Demo internal task", "production")
        for state in ("screened", "queued"):
            self.store.transition(task["task_id"], state, actor="test")
        hits = []
        def mock_worker(payload):
            hits.append(payload["task_id"])
            if len(hits) == 1:
                raise RateLimited("mock 429")
            return WorkResult("mock://result", "done")
        dispatcher = Dispatcher(self.store, workers={"mock": mock_worker})
        runner = QueueRunner(self.store, dispatcher, worker_by_department={"production": "mock"})
        self.assertEqual(runner.tick()[0]["state"], "rate_limited")
        self.retry.schedule(task["task_id"], error="mock 429", at=T0)
        self.assertEqual(runner.tick(), [])
        self.assertEqual(self.retry.requeue_due(at=T0 + timedelta(seconds=11)), [task["task_id"]])
        self.assertEqual(runner.tick()[0]["state"], "reviewing")
        self.assertEqual(self.store.get(task["task_id"])["state"], "reviewing")
        self.assertEqual(len(hits), 2)
        dispatcher.approve_review(task["task_id"], reviewer="qa")
        self.assertEqual(self.store.get(task["task_id"])["state"], "completed")

    def test_external_action_denied_even_with_volatile_approval(self):
        task = self.store.create("demo", "External action", "sales")
        for state in ("screened", "queued"):
            self.store.transition(task["task_id"], state, actor="test")
        hits = []
        dispatcher = Dispatcher(self.store, workers={"mock": lambda _: hits.append("executed")},
                                approvals={(task["task_id"], "send_email")})
        from hub.dispatcher import ApprovalRequired
        with self.assertRaises(ApprovalRequired):
            dispatcher.run(task["task_id"], "mock", action="send_email")
        self.assertEqual(hits, [])
        self.assertEqual(self.store.get(task["task_id"])["state"], "awaiting_approval")
