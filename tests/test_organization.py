import tempfile
import unittest
from pathlib import Path
from hub.task_store import TaskStore
from hub.organization import Organization

class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=TaskStore(Path(self.tmp.name)/"org.sqlite")
        self.org=Organization(self.store)
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def test_delegation_and_report(self):
        plan=self.org.delegate("demo",scenario="website_prototype")
        self.assertEqual(len(plan),4)
        self.assertEqual(len(self.org.control.ready()),1)
        self.assertEqual(self.org.executive_report("demo")["overall"]["total"],4)
        self.assertEqual(set(x["manager"] for x in plan),
                         {"sales_manager","production_manager","qa_manager","admin_manager"})
    def test_idempotent_delegation(self):
        first=self.org.delegate("demo",scenario="research_report")
        second=self.org.delegate("demo",scenario="research_report")
        self.assertEqual(first,second)
        self.assertEqual(len(self.store.list_tasks("demo")),4)
    def test_reject_unauthorized(self):
        with self.assertRaises(PermissionError):
            self.org.delegate("demo",scenario="website_prototype",manager="worker")
    def test_reject_unknown_scenario(self):
        with self.assertRaises(ValueError):
            self.org.delegate("demo",scenario="real_crowdworks_application")
