import tempfile
import unittest
from pathlib import Path
from hub.task_store import TaskStore
from hub.dispatcher import Dispatcher, WorkResult
from hub.queue_runner import QueueRunner

class QueueRunnerTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.t.name)/"tasks.sqlite")

    def tearDown(self):
        self.store.close()
        self.t.cleanup()

    def add_queued(self, dept):
        task = self.store.create("demo", "Mock task", dept)
        self.store.transition(task["task_id"], "screened", actor="test")
        self.store.transition(task["task_id"], "queued", actor="test")
        return task["task_id"]

    def test_bounded_dispatch_only_approved_department(self):
        ids = [self.add_queued("production") for _ in range(3)]
        unknown = self.add_queued("unknown")
        dispatcher = Dispatcher(self.store, workers={"mock": lambda data: WorkResult("mock://"+data["task_id"])})
        runner = QueueRunner(self.store, dispatcher, worker_by_department={"production": "mock"})
        results = runner.tick(max_tasks=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(self.store.get(i)["state"]=="reviewing" for i in ids), 2)
        self.assertEqual(self.store.get(unknown)["state"], "queued")
        self.assertEqual(len(runner.tick(max_tasks=5)), 1)

    def test_worker_result_does_not_auto_complete(self):
        id = self.add_queued("production")
        dispatcher = Dispatcher(self.store, workers={"mock": lambda _: WorkResult("mock://artifact")})
        runner = QueueRunner(self.store, dispatcher, worker_by_department={"production": "mock"})
        runner.tick()
        self.assertEqual(self.store.get(id)["state"], "reviewing")

    def test_bad_batch_limit_rejected(self):
        dispatcher = Dispatcher(self.store, workers={})
        runner = QueueRunner(self.store, dispatcher, worker_by_department={})
        with self.assertRaises(ValueError):
            runner.tick(max_tasks=0)
