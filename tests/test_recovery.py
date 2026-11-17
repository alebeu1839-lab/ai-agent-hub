import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from hub.task_store import TaskStore
from hub.control_plane import ControlPlane
from hub.recovery import RecoveryController

T0 = datetime(2026, 11, 17, tzinfo=timezone.utc)

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.tmp.name) / "tasks.db")
        self.control = ControlPlane(self.store)
        self.recovery = RecoveryController(self.store, self.control)
        task = self.store.create("demo", "mock", "production")
        self.task_id = task["task_id"]
        self.store.transition(self.task_id, "screened", actor="test")
        self.store.transition(self.task_id, "queued", actor="test")
        self.assertTrue(self.control.claim(self.task_id, "worker-a",
                                           at=T0, ttl_seconds=10))
        self.store.transition(self.task_id, "running", actor="worker-a")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_no_early_quarantine(self):
        self.assertEqual(self.recovery.inspect(at=T0 + timedelta(seconds=5)), [])
        self.assertEqual(self.recovery.quarantine(at=T0 + timedelta(seconds=5)), [])

    def test_stale_quarantine_retains_lease(self):
        later = T0 + timedelta(seconds=11)
        self.assertEqual(len(self.recovery.inspect(at=later)), 1)
        self.assertEqual(self.recovery.quarantine(at=later), [self.task_id])
        self.assertEqual(self.store.get(self.task_id)["state"], "blocked")
        self.assertFalse(self.control.claim(self.task_id, "worker-b", at=later))
        self.assertEqual(self.recovery.quarantine(at=later), [])

    def test_release_requires_verification(self):
        self.recovery.quarantine(at=T0 + timedelta(seconds=11))
        with self.assertRaises(PermissionError):
            self.recovery.release_verified(self.task_id, "worker-a", operator="owner")
        with self.assertRaises(ValueError):
            self.recovery.release_verified(self.task_id, "worker-b",
                                           operator="owner", confirmed_stopped=True)
        self.assertTrue(self.recovery.release_verified(
            self.task_id, "worker-a", operator="owner", confirmed_stopped=True))
        self.assertEqual(self.store.get(self.task_id)["state"], "blocked")
        self.assertIn("verified worker stopped", self.store.history(self.task_id)[-1]["note"])
