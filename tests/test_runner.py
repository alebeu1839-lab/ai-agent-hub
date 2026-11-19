"""End-to-end tests against local bare git repos (stand-in for GitHub).

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hub import config as hubconfig
from hub.codex_mcp_bridge import handle
from hub.redact import redact
from hub.runner import Runner

ROOT = Path(__file__).resolve().parent.parent
FAKES = ROOT / "tests" / "fakes"


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


class Env:
    """A bare repo with `main` (target code) and `agent-queue` (task queue) branches."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.bare = tmp / "origin.git"
        sh("git", "init", "--quiet", "--bare", "-b", "main", str(self.bare))
        seed = tmp / "seed"
        sh("git", "clone", "--quiet", str(self.bare), str(seed))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            sh("git", "config", k, v, cwd=seed)
        (seed / "README.md").write_text("target repo\n")
        sh("git", "add", ".", cwd=seed)
        sh("git", "commit", "--quiet", "-m", "init", cwd=seed)
        sh("git", "push", "--quiet", "origin", "HEAD:main", cwd=seed)
        sh("git", "checkout", "--quiet", "--orphan", "agent-queue", cwd=seed)
        sh("git", "rm", "-rfq", ".", cwd=seed)
        (seed / "queue" / "inbox").mkdir(parents=True)
        (seed / "queue" / "inbox" / ".gitkeep").write_text("")
        sh("git", "add", ".", cwd=seed)
        sh("git", "commit", "--quiet", "-m", "queue init", cwd=seed)
        sh("git", "push", "--quiet", "origin", "HEAD:agent-queue", cwd=seed)
        self.seed = seed
        self.cfg = hubconfig._merge(hubconfig.DEFAULTS, {
            "runner_id": "test-runner",
            "queue_repo_url": str(self.bare),
            "queue_branch": "agent-queue",
            "allowed_repos": {"owner/target": {"clone_url": str(self.bare),
                                               "allowed_base_branches": ["main", "feat/*"]}},
            "allowed_modes": ["plan", "implement"],
            "security": {"require_verified_commit": False, "allowed_submitters": ["owner"],
                         "max_instruction_chars": 8000},
            "retry": {"max_attempts": 2, "base_backoff_sec": 60, "max_backoff_sec": 600,
                      "usage_limit_cooldown_sec": 900},
            "state_dir": str(tmp / "state"),
        })

    def submit(self, task: dict, path_state="inbox"):
        """What GPT does: commit a task JSON file to the queue branch."""
        sh("git", "fetch", "--quiet", "origin", "agent-queue", cwd=self.seed)
        sh("git", "reset", "--quiet", "--hard", "origin/agent-queue", cwd=self.seed)
        p = self.seed / "queue" / path_state / f"{task['id']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(task))
        sh("git", "add", ".", cwd=self.seed)
        sh("git", "commit", "--quiet", "-m", f"task {task['id']}", cwd=self.seed)
        sh("git", "push", "--quiet", "origin", "HEAD:agent-queue", cwd=self.seed)

    def read_queue(self, rel: str) -> str:
        return sh("git", "--git-dir", str(self.bare), "show", f"agent-queue:queue/{rel}")

    def exists(self, rel: str) -> bool:
        return subprocess.run(["git", "--git-dir", str(self.bare), "cat-file", "-e", f"agent-queue:queue/{rel}"],
                              capture_output=True).returncode == 0


def task(tid="t-001", **kw):
    t = {"id": tid, "title": "test task", "instructions": "Add a marker file.", "repo": "owner/target",
         "base_branch": "main", "mode": "implement", "requested_by": "gpt"}
    t.update(kw)
    return t


class RunnerE2E(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.env = Env(Path(self._td.name))
        os.environ["CLAUDE_BIN"] = str(FAKES / "fake_claude.py")
        os.environ["CODEX_BIN"] = str(FAKES / "fake_codex.py")
        for k in ("FAKE_CLAUDE_MODE", "FAKE_CODEX_MODE"):
            os.environ.pop(k, None)

    def tearDown(self):
        self._td.cleanup()

    def runner(self, verifier=None):
        return Runner(self.env.cfg, verifier=verifier)

    def test_implement_task_end_to_end(self):
        self.env.submit(task())
        self.assertEqual(self.runner().run_once(), "done")
        self.assertTrue(self.env.exists("done/t-001.json"))
        report = self.env.read_queue("results/t-001/report.md")
        self.assertIn("Status:** done", report)
        self.assertIn("codex_implement:ok", report)
        self.assertIn("Implemented: created CODEX_WAS_HERE.md", report)
        result = json.loads(self.env.read_queue("results/t-001/result.json"))
        self.assertTrue(result["git"]["pushed"])
        # work branch has Codex's file; main is untouched
        files = sh("git", "--git-dir", str(self.env.bare), "ls-tree", "--name-only", "agent/t-001")
        self.assertIn("CODEX_WAS_HERE.md", files)
        main_files = sh("git", "--git-dir", str(self.env.bare), "ls-tree", "--name-only", "main")
        self.assertNotIn("CODEX_WAS_HERE.md", main_files)
        self.assertIn("t-001", self.env.read_queue("status.md"))
        self.assertEqual(self.runner().run_once(), "idle")

    def test_plan_task_is_read_only(self):
        self.env.submit(task("p-001", mode="plan"))
        self.assertEqual(self.runner().run_once(), "done")
        result = json.loads(self.env.read_queue("results/p-001/result.json"))
        self.assertEqual(result["codex_calls"][0]["tool"], "codex_review")
        self.assertEqual(result["codex_calls"][0]["sandbox"], "read-only")
        self.assertFalse(result["git"]["pushed"])  # nothing changed -> nothing pushed

    def test_rejects_disallowed_tasks(self):
        self.env.submit(task("bad-repo", repo="someone/else"))
        self.env.submit(task("bad-base", base_branch="production"))
        self.env.submit(task("bad-mode", mode="deploy"))
        self.env.submit(task("bad-field", shell="rm -rf /"))
        r = self.runner()
        self.assertEqual(r.run_once(), "idle")
        for tid in ("bad-repo", "bad-base", "bad-mode", "bad-field"):
            self.assertTrue(self.env.exists(f"failed/{tid}.json"), tid)
            self.assertIn("REJECTED", self.env.read_queue(f"results/{tid}/report.md"))

    def test_unverified_submitter_rejected(self):
        self.env.cfg["security"]["require_verified_commit"] = True
        self.env.cfg["queue_repo_url"] = str(self.env.bare)  # not github -> cannot verify -> fail closed
        self.env.submit(task("u-001"))
        self.assertEqual(self.runner().run_once(), "idle")
        self.assertIn("unauthorised", self.env.read_queue("results/u-001/report.md"))

    def test_verifier_called_for_github_queue(self):
        calls = []

        def verifier(slug, sha, allowed):
            calls.append((slug, sha, allowed))
            return False, "commit is not GitHub-verified"
        self.env.cfg["security"]["require_verified_commit"] = True
        r = self.runner(verifier)
        r.cfg["queue_repo_url"] = "https://github.com/owner/queue.git"
        r.queue.repo_url = str(self.env.bare)  # transport stays local
        self.env.submit(task("v-001"))
        self.assertEqual(r.run_once(), "idle")
        self.assertEqual(calls[0][0], "owner/queue")
        self.assertEqual(calls[0][2], ["owner"])
        self.assertTrue(self.env.exists("failed/v-001.json"))

    def test_transient_error_retries_then_fails(self):
        os.environ["FAKE_CLAUDE_MODE"] = "rate_limit"
        self.env.submit(task("r-001"))
        r = self.runner()
        self.assertEqual(r.run_once(), "retry_scheduled")
        t = json.loads(self.env.read_queue("inbox/r-001.json"))
        self.assertEqual(t["_state"]["attempts"], 1)
        self.assertTrue(t["_state"]["not_before"])
        self.assertEqual(r.run_once(), "idle")  # backoff not expired
        # expire the backoff and retry: max_attempts=2 -> failed
        t["_state"]["not_before"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.env.submit(t)
        self.assertEqual(r.run_once(), "failed")
        self.assertTrue(self.env.exists("failed/r-001.json"))

    def test_codex_usage_limit_is_reported(self):
        os.environ["FAKE_CODEX_MODE"] = "usage_limit"
        self.env.submit(task("c-001"))
        self.assertEqual(self.runner().run_once(), "done")
        result = json.loads(self.env.read_queue("results/c-001/result.json"))
        self.assertEqual(result["codex_calls"][0]["error_kind"], "usage_limit")
        self.assertIn("codex_implement:usage_limit", self.env.read_queue("results/c-001/report.md"))

    def test_codex_not_logged_in_fails_fast(self):
        os.environ["FAKE_CODEX_MODE"] = "auth"
        self.env.submit(task("a-001"))
        self.assertEqual(self.runner().run_once(), "done")
        result = json.loads(self.env.read_queue("results/a-001/result.json"))
        self.assertEqual(result["codex_calls"][0]["error_kind"], "auth")
        self.assertTrue(any("no successful Codex call" in w for w in result["warnings"]))

    def test_pause_switch(self):
        self.env.submit(task("s-001"))
        sh("git", "fetch", "--quiet", "origin", "agent-queue", cwd=self.env.seed)
        sh("git", "reset", "--quiet", "--hard", "origin/agent-queue", cwd=self.env.seed)
        (self.env.seed / "queue" / "PAUSE").write_text("stop\n")
        sh("git", "add", ".", cwd=self.env.seed)
        sh("git", "commit", "--quiet", "-m", "pause", cwd=self.env.seed)
        sh("git", "push", "--quiet", "origin", "HEAD:agent-queue", cwd=self.env.seed)
        self.assertEqual(self.runner().run_once(), "paused")
        self.assertTrue(self.env.exists("inbox/s-001.json"))

    def test_resume_after_crash(self):
        t = task("k-001")
        t["_state"] = {"status": "running", "runner": "test-runner", "attempts": 1}
        self.env.submit(t, path_state="running")
        self.assertEqual(self.runner().run_once(), "done")
        self.assertTrue(self.env.exists("done/k-001.json"))

    def test_other_runners_task_not_stolen(self):
        t = task("o-001")
        t["_state"] = {"status": "running", "runner": "someone-else", "attempts": 1}
        self.env.submit(t, path_state="running")
        self.assertEqual(self.runner().run_once(), "idle")

    def test_usage_limit_cooldown(self):
        r = self.runner()
        r.set_cooldown(600, "test")
        self.env.submit(task("w-001"))
        self.assertTrue(r.run_once().startswith("cooldown"))


class Units(unittest.TestCase):
    def test_redact(self):
        s = "token ghp_" + "a" * 36 + " key sk-ant-abcdefghijklmnop password=hunter22 https://u:p@host/x"
        out = redact(s)
        for bad in ("ghp_aaaa", "sk-ant-abcdef", "hunter22", "u:p@"):
            self.assertNotIn(bad, out)

    def test_bridge_blocks_write_tools_in_plan_mode(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ.update({"CODEX_BRIDGE_WORKSPACE": td, "CODEX_BRIDGE_MAX_SANDBOX": "read-only"})
            r = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "codex_implement", "arguments": {"instructions": "x"}}})
            self.assertTrue(r["result"]["isError"])
            self.assertIn("forbidden", r["result"]["content"][0]["text"])
            r = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            self.assertEqual({t["name"] for t in r["result"]["tools"]},
                             {"codex_implement", "codex_test", "codex_review"})

    def test_task_validation_defaults(self):
        cfg = hubconfig._merge(hubconfig.DEFAULTS, {"allowed_repos": {"a/b": {"allowed_base_branches": ["main"]}}})
        t = hubconfig.validate_task({"id": "abc", "instructions": "x", "repo": "a/b"}, cfg)
        self.assertEqual((t["mode"], t["base_branch"], t["work_branch"]), ("plan", "main", "agent/abc"))
        with self.assertRaises(hubconfig.TaskRejected):  # implement disabled by default
            hubconfig.validate_task({"id": "abc", "instructions": "x", "repo": "a/b", "mode": "implement"}, cfg)
        with self.assertRaises(hubconfig.TaskRejected):
            hubconfig.validate_task({"id": "../etc", "instructions": "x", "repo": "a/b"}, cfg)


if __name__ == "__main__":
    unittest.main()
