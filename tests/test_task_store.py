import tempfile
import unittest
from pathlib import Path
from hub.task_store import TaskStore

class TestTaskStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.sqlite"
        self.store = TaskStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_persist_dedupe_audit(self):
        item = self.store.create("crowdworks", "Mock site", "production", key="job-1")
        self.assertEqual(item["task_id"], self.store.create("crowdworks", "Mock site", "production", key="job-1")["task_id"])
        for state, actor in [("screened","manager"),("queued","manager"),("running","worker")]:
            self.store.transition(item["task_id"], state, actor=actor)
        self.store.transition(item["task_id"], "reviewing", actor="worker", output_ref="mock/output")
        self.store.transition(item["task_id"], "completed", actor="qa")
        self.assertEqual(len(self.store.history(item["task_id"])), 6)
        self.store.close()
        self.store = TaskStore(self.path)
        self.assertEqual(self.store.get(item["task_id"])["state"], "completed")

    def test_reject_invalid_actions(self):
        item = self.store.create("p", "t", "sales", key="key")
        with self.assertRaises(ValueError):
            self.store.transition(item["task_id"], "completed", actor="system")
        with self.assertRaises(ValueError):
            self.store.create("p", "different", "sales", key="key")

    def test_rate_limit_and_retry(self):
        item = self.store.create("p", "t", "qa")
        for state in ("screened","queued","running","rate_limited","retry_scheduled","queued","running","reviewing","queued"):
            self.store.transition(item["task_id"], state, actor="system")
        self.assertEqual(self.store.get(item["task_id"])["state"], "queued")

if __name__ == "__main__":
    unittest.main()
