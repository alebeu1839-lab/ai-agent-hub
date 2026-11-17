import unittest
from pathlib import Path
from types import SimpleNamespace
from hub.cli_adapter import CLIAdapter,CLIConfig

class CLITests(unittest.TestCase):
    def test_disabled_by_default(self):
        with self.assertRaises(PermissionError):
            CLIAdapter(CLIConfig("codex","codex"))({"task_id":"mock","instruction":"internal"})
    def test_fixed_command_no_shell(self):
        calls=[]
        def runner(argv,**kwargs):
            calls.append((argv,kwargs))
            return SimpleNamespace(returncode=0,stdout="OK")
        adapter=CLIAdapter(CLIConfig("mock","mock-cli",("--internal-mode",),".",5,True),runner=runner)
        result=adapter({"task_id":"t","instruction":"do this"})
        self.assertEqual(result.output_ref,"unpersisted://t")
        self.assertEqual(calls[0][0],["mock-cli","--internal-mode"])
        self.assertEqual(calls[0][1]["input"],"do this")
        self.assertNotIn("shell",calls[0][1])
    def test_missing_instruction(self):
        adapter=CLIAdapter(CLIConfig("mock","mock-cli",enabled=True))
        with self.assertRaises(ValueError):
            adapter({"task_id":"t"})
    def test_failure_no_stderr_leak(self):
        def runner(*args,**kwargs):
            return SimpleNamespace(returncode=1,stdout="",stderr="SECRET")
        adapter=CLIAdapter(CLIConfig("mock","mock-cli",enabled=True),runner=runner)
        with self.assertRaises(RuntimeError) as err:
            adapter({"task_id":"t","instruction":"test"})
        self.assertNotIn("SECRET",str(err.exception))
