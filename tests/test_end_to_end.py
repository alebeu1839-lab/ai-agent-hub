import tempfile
import unittest
from pathlib import Path
from hub.demo import demo

class EndToEndTests(unittest.TestCase):
    def test_four_departments_end_to_end(self):
        report=demo()
        self.assertEqual(report["overall"]["states"]["completed"],4)
        self.assertEqual(len(report["departments"]),4)
        self.assertFalse(report["requires_owner_attention"])
    def test_html_artifact_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"report.html"
            demo(path)
            self.assertTrue(path.is_file())
            self.assertIn("Total tasks: 4",path.read_text(encoding="utf-8"))
