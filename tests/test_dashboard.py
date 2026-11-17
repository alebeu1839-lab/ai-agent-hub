import tempfile
import unittest
from pathlib import Path
from hub.task_store import TaskStore
from hub.dashboard import render_dashboard, write_dashboard

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)
        self.store=TaskStore(self.path/"db.sqlite")
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def test_counts_and_escaped_html(self):
        self.store.create("demo","<script>alert(1)</script>","qa")
        text=render_dashboard(self.store,project_id="demo")
        self.assertIn("Total tasks: 1",text)
        self.assertNotIn("<script>",text)
        self.assertIn("&lt;script&gt;",text)
    def test_write_local_only(self):
        output=write_dashboard(self.store,self.path/"report.html")
        self.assertTrue(output.exists())
        self.assertIn("No tasks yet",output.read_text())
    def test_reject_bad_extension(self):
        with self.assertRaises(ValueError):
            write_dashboard(self.store,self.path/"report.py")
