import json, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock
from agent_queue import run_queue

class AgentQueueTests(unittest.TestCase):
    def test_sequential_review_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "queue.json"
            path.write_text(json.dumps({"tasks": [
                {"id": "first", "state": "pending"},
                {"id": "second", "state": "pending", "depends_on": ["first"]},
                {"id": "third", "state": "pending", "requires_approval": True}
            ]}))
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                return Mock(returncode=0, stdout="", stderr="")
            result = run_queue(path, {"implement": ["echo", "i"], "review": ["echo", "r"]}, runner)
            self.assertEqual([t["state"] for t in result["tasks"]], ["completed", "completed", "waiting_approval"])
            self.assertEqual([c[-1] for c in calls], ["first", "first", "second", "second"])

    def test_interrupted_does_not_rerun(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "queue.json"
            path.write_text(json.dumps({"tasks": [{"id": "a", "state": "implementing"}]}))
            result = run_queue(path, {}, lambda *a, **k: self.fail("rerun"))
            self.assertEqual(result["tasks"][0]["state"], "waiting_approval")

    def test_no_unconfigured_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "queue.json"
            path.write_text(json.dumps({"tasks": [{"id": "a", "state": "pending"}]}))
            result = run_queue(path, {}, lambda *a, **k: self.fail("executed"))
            self.assertEqual(result["tasks"][0]["state"], "waiting_approval")

if __name__ == "__main__":
    unittest.main()
