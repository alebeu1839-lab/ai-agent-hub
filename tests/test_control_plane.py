import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from hub.task_store import TaskStore
from hub.control_plane import ControlPlane

T=datetime(2026,11,17,tzinfo=timezone.utc)

class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=TaskStore(Path(self.tmp.name)/"db.sqlite")
        self.control=ControlPlane(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def task(self, state="queued"):
        t=self.store.create("demo","mock","production")
        if state!="created":
            self.store.transition(t["task_id"],"screened",actor="test")
            if state!="screened":
                self.store.transition(t["task_id"],"queued",actor="test")
        return t["task_id"]

    def test_01_roles(self):
        self.assertTrue(self.control.allow("ceo","plan"))
        self.assertFalse(self.control.allow("worker","assign"))
        self.assertFalse(self.control.allow("unknown","execute"))

    def test_02_budget(self):
        self.assertEqual(self.control.set_budget("demo",100)["cap"],100)
        with self.assertRaises(ValueError): self.control.set_budget("demo",-1)

    def test_03_charge_cap(self):
        self.control.set_budget("demo",50)
        self.assertEqual(self.control.charge("demo",30)["spent"],30)
        with self.assertRaises(PermissionError): self.control.charge("demo",21)

    def test_04_snapshot(self):
        self.assertIsNone(self.control.budget("absent"))

    def test_05_dependency_cycle(self):
        a,b=self.task(),self.task()
        self.control.depend_on(b,a)
        with self.assertRaises(ValueError): self.control.depend_on(a,b)
        self.assertEqual([r["task_id"] for r in self.control.ready()],[a])

    def test_06_priority(self):
        a,b=self.task(),self.task()
        self.control.prioritize(b,50)
        self.assertEqual(self.control.ready()[0]["task_id"],b)
        with self.assertRaises(ValueError): self.control.prioritize(a,101)

    def test_07_ready_blocks_until_completed(self):
        a,b=self.task(),self.task()
        self.control.depend_on(b,a)
        self.assertEqual(len(self.control.ready()),1)
        self.store.transition(a,"running",actor="test")
        self.store.transition(a,"reviewing",actor="test",output_ref="mock://output")
        self.store.transition(a,"completed",actor="qa")
        self.assertEqual(len(self.control.ready()),1)

    def test_08_exclusive_lease(self):
        a=self.task()
        self.assertTrue(self.control.claim(a,"worker-1",at=T))
        self.assertFalse(self.control.claim(a,"worker-2",at=T))

    def test_09_heartbeat(self):
        a=self.task()
        self.control.claim(a,"worker-1",at=T)
        self.assertFalse(self.control.heartbeat(a,"wrong",at=T))
        self.assertTrue(self.control.heartbeat(a,"worker-1",at=T+timedelta(seconds=20)))

    def test_10_expired_and_release(self):
        a=self.task()
        self.control.claim(a,"worker-1",at=T,ttl_seconds=10)
        self.assertEqual(len(self.control.expired_leases(at=T+timedelta(seconds=11))),1)
        self.assertFalse(self.control.release(a,"worker-2"))
        self.assertTrue(self.control.release(a,"worker-1"))

    def test_dashboard(self):
        self.task()
        self.assertEqual(self.control.dashboard("demo")["states"]["queued"],1)

if __name__=="__main__":
    unittest.main()
