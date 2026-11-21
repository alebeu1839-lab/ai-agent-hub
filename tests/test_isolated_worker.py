import json
import io
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from hub.addness import FakeAddnessClient
from hub.addness_intake import AddnessBridge
from hub.config import DEFAULTS as HUB_DEFAULTS
from hub.isolated_worker import (
    IsolatedWorker, Lease, LeaseMismatch, Request, WorkerConfigError,
    load_worker_config, main,
)

HEAD = "a" * 40
HEAD2 = "b" * 40
HEAD3 = "c" * 40
SOURCE = "afe1fa15-e2d2-41fc-a6c0-86b8a9eefcf2"
BRIDGE = "655c2d75-6c62-4c43-98d5-bd61c5aad9f9"
REPO = "alebeu1839-lab/-my-addness"
BRANCH = "codex/today-bulk-selection"


class IsolatedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "config" / "my-addness-worker.json"
        self.config_path.parent.mkdir()
        self.store_path = self.root / "goals.json"
        self.store_path.write_text(json.dumps({"goals": {
            SOURCE: {"id": SOURCE, "title": "Source", "body": "", "comments": [], "path": ["My Addness", "Source"]},
            BRIDGE: {"id": BRIDGE, "title": "Bridge", "body": "", "comments": [], "path": ["Bridge"]},
        }}), encoding="utf-8")
        self.raw_cfg = {
            "enabled": True, "execute_enabled": True, "state_dir": "state-isolated/my-addness",
            "addness": {"client": "fake", "fake_store": str(self.store_path)},
        }
        self.config_path.write_text(json.dumps(self.raw_cfg), encoding="utf-8")
        self.cfg = load_worker_config(self.config_path, self.root / "state")
        self.client = FakeAddnessClient(self.store_path)
        self.remote = HEAD
        self.worker = IsolatedWorker(self.cfg, self.client, lambda url, branch: self.remote)

    def tearDown(self): self.tmp.cleanup()

    def request(self, *, run="run-001", repo=REPO, branch=BRANCH, pr=2, goal=SOURCE, mode="inspect", expected=None):
        return Request(run, repo, branch, pr, goal, expected, mode)

    def test_allowed_inspect_dry_run_and_execute_writeback(self):
        self.assertEqual(self.worker.admit(self.request()).reason, "ok")
        dry = self.worker.dry_run(self.request(mode="dry-run"))
        self.assertTrue(dry["decision"]["ok"])
        self.assertFalse((Path(self.cfg["state_dir"]) / "lease.json").exists())
        result = self.worker.process(self.request(mode="execute"), lambda ctx: {"head": ctx["head"]})
        self.assertEqual(result["status"], "done")
        source = self.client.get_task(SOURCE)
        self.assertIn(f"[my-addness-worker:done run=run-001 status=done sha={HEAD}]", "\n".join(c["body"] for c in source["comments"]))
        self.assertIn(f"[my-addness-worker:checkpoint run=run-001 sha={HEAD} phase=done]", "\n".join(c["body"] for c in source["comments"]))
        self.assertIn(HEAD, source["body"])
        bridge = self.client.get_task(BRIDGE)
        self.assertIn("[my-addness-worker:progress", "\n".join(c["body"] for c in bridge["comments"]))
        self.assertFalse((Path(self.cfg["state_dir"]) / "lease.json").exists())

    def test_admission_rejections(self):
        cases = [
            (self.request(repo="alebeu1839-lab/ai-agent-hub"), "repo not allowed"),
            (self.request(repo="ALEBEU1839-lab/-my-addness"), "repo not allowed"),
            (self.request(branch="main"), "branch not allowed"),
            (self.request(branch="other"), "branch not allowed"),
            (self.request(pr=3), "pr denied"),
            (self.request(pr=4), "pr not allowed"),
            (self.request(pr=None, mode="dry-run"), "pr required"),
            (self.request(goal="wrong"), "goal not allowed"),
            (self.request(run="x"), "invalid run_id"),
        ]
        for req, reason in cases:
            with self.subTest(reason=reason, req=req): self.assertEqual(self.worker.admit(req).reason, reason)
        self.cfg["execute_enabled"] = False
        self.assertEqual(self.worker.admit(self.request(mode="execute")).reason, "execute not enabled")
        self.cfg["enabled"] = False
        self.assertEqual(self.worker.admit(self.request(mode="dry-run")).reason, "worker disabled")
        self.assertTrue(self.worker.admit(self.request(mode="inspect")).ok)

    def test_config_validation_and_path_isolation(self):
        for patch, expected in [
            ({"target_branch": "main"}, "target_branch denied"),
            ({"target_pr": 3}, "target_pr denied"),
            ({"target_branch": "feat/*"}, "target_branch invalid"),
            ({"state_dir": "state"}, "state_dir overlaps"),
            ({"state_dir": "state/isolated/x"}, "state_dir overlaps"),
        ]:
            raw = dict(self.raw_cfg); raw.update(patch)
            self.config_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.subTest(patch=patch), self.assertRaisesRegex(WorkerConfigError, expected):
                load_worker_config(self.config_path, self.root / "state")
        self.config_path.write_text(json.dumps(self.raw_cfg), encoding="utf-8")
        cfg = load_worker_config(self.config_path, self.root / "state")
        self.assertNotEqual(Path(cfg["state_dir"]), self.root / "state")
        self.assertNotIn(self.root / "state", Path(cfg["state_dir"]).parents)

    def test_config_rejects_clone_url_userinfo_without_echoing_url(self):
        secret_url = "https://user:tok@github.com/x/y.git"
        raw = dict(self.raw_cfg)
        raw["target_clone_url"] = secret_url
        self.config_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(WorkerConfigError) as raised:
            load_worker_config(self.config_path, self.root / "state")
        self.assertEqual(str(raised.exception), "target_clone_url invalid")
        self.assertNotIn(secret_url, str(raised.exception))

    def test_running_without_lease_requires_current_head_checkpoint(self):
        run_id = "running-001"
        state_dir = Path(self.cfg["state_dir"])
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / "state.json"
        original_state = {"runs": {run_id: {"status": "running", "phase": "execute"}}}
        state_path.write_text(json.dumps(original_state), encoding="utf-8")
        comments_before = list(self.client.get_task(SOURCE)["comments"])
        called = []

        result = self.worker.process(
            self.request(run=run_id, mode="execute"),
            lambda ctx: called.append(ctx) or {"head": HEAD},
        )

        self.assertEqual(result, {"status": "rejected", "reason": "stale running run: checkpoint required"})
        self.assertEqual(called, [])
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), original_state)
        self.assertEqual(comments_before, self.client.get_task(SOURCE)["comments"])

        self.client.add_comment(SOURCE, f"[my-addness-worker:checkpoint run={run_id} sha={HEAD} phase=review]")
        completed = self.worker.process(
            self.request(run=run_id, mode="execute"), lambda ctx: {"head": ctx["head"]}
        )
        self.assertEqual(completed, {"status": "done", "head": HEAD})

    def test_duplicate_lock_lease_expiry_and_manual_release(self):
        self.worker.process(self.request(mode="execute"), lambda ctx: {"head": HEAD})
        self.assertEqual(self.worker.admit(self.request()).reason, "duplicate run_id")
        lease_path = Path(self.cfg["state_dir"]) / "lease.json"
        lease = Lease(lease_path, 3600)
        lease.acquire("held-001", "operator")
        self.assertEqual(self.worker.admit(self.request(run="other-001")).reason, "active lease")
        with self.assertRaises(LeaseMismatch): lease.manual_release("wrong-001")
        lease.manual_release("held-001")
        lease_path.write_text(json.dumps({"run_id": "old-001", "holder": "old", "expires_at": time.time() - 1}), encoding="utf-8")
        self.assertEqual(self.worker.admit(self.request(run="new-001")).reason, "expired lease: manual release required")
        self.assertTrue(lease_path.exists())
        lease.manual_release("old-001")
        lock_path = Path(self.cfg["state_dir"]) / "worker.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True); lock_path.write_text("held")
        self.assertEqual(self.worker.process(self.request(run="locked-001", mode="execute"), lambda ctx: {"head": HEAD})["status"], "locked")

    def test_duplicate_state_after_prior_admission_is_not_overwritten(self):
        req = self.request(run="duplicate-001", mode="execute")
        self.assertTrue(self.worker.admit(req).ok)
        state_dir = Path(self.cfg["state_dir"])
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / "state.json"
        state_path.write_text(json.dumps({"runs": {}}), encoding="utf-8")
        comments_before = list(self.client.get_task(SOURCE)["comments"])
        acquire = self.worker.lease.acquire

        def acquire_and_complete(run_id, holder):
            result = acquire(run_id, holder)
            completed_state = {
                "runs": {
                    req.run_id: {
                        "status": "done", "phase": "done", "checkpoint_sha": HEAD,
                    }
                }
            }
            state_path.write_text(json.dumps(completed_state), encoding="utf-8")
            return result

        self.worker.lease.acquire = acquire_and_complete

        result = self.worker.process(req, lambda ctx: {"head": HEAD})

        self.assertEqual(result, {"status": "rejected", "reason": "duplicate run_id"})
        completed_state = {
            "runs": {req.run_id: {"status": "done", "phase": "done", "checkpoint_sha": HEAD}}
        }
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), completed_state)
        self.assertFalse((state_dir / "lease.json").exists())
        self.assertEqual(comments_before, self.client.get_task(SOURCE)["comments"])

    def test_invalid_second_head_resolution_rejects_before_lease_without_writeback(self):
        calls = 0
        def becomes_unknown(*_):
            nonlocal calls
            calls += 1
            return HEAD if calls <= 2 else None
        worker = IsolatedWorker(self.cfg, self.client, becomes_unknown)
        comments_before = list(self.client.get_task(SOURCE)["comments"])

        result = worker.process(self.request(run="unknown-001", mode="execute"), lambda ctx: {"head": HEAD})

        self.assertEqual(result, {"status": "rejected", "reason": "head unknown"})
        self.assertFalse((Path(self.cfg["state_dir"]) / "lease.json").exists())
        self.assertFalse((Path(self.cfg["state_dir"]) / "state.json").exists())
        self.assertEqual(comments_before, self.client.get_task(SOURCE)["comments"])

    def test_release_lease_without_run_id_is_refused(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--config", str(self.config_path), "release-lease"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"status": "refused", "reason": "run_id required"})

    def test_head_unknown_mismatch_and_race(self):
        unknown = IsolatedWorker(self.cfg, self.client, lambda *_: (_ for _ in ()).throw(OSError()))
        self.assertEqual(unknown.admit(self.request()).reason, "head unknown")
        self.assertEqual(self.worker.admit(self.request(expected=HEAD2)).reason, "head mismatch")

        moving_head = IsolatedWorker(self.cfg, self.client, lambda *_: HEAD)
        def advancing_executor(ctx):
            moving_head.head_resolver = lambda *_: HEAD2
            return {"head": HEAD2}
        advanced = moving_head.process(
            self.request(run="advance-001", mode="execute"), advancing_executor
        )
        self.assertEqual(advanced, {"status": "done", "head": HEAD2})
        self.assertEqual(moving_head.status()["runs"]["advance-001"]["checkpoint_sha"], HEAD2)

        n = 0
        def third_head(*_):
            nonlocal n
            n += 1
            return HEAD3 if n >= 4 else HEAD
        racer = IsolatedWorker(self.cfg, self.client, third_head)
        result = racer.process(self.request(run="race-001", mode="execute"), lambda ctx: {"head": HEAD})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "head race")
        self.assertFalse((Path(self.cfg["state_dir"]) / "lease.json").exists())
        self.assertEqual(racer.status()["runs"]["race-001"]["status"], "failed")
        self.assertIn("[my-addness-worker:failed run=race-001", "\n".join(c["body"] for c in self.client.get_task(SOURCE)["comments"]))

    def test_interruption_and_resume_checkpoint(self):
        with self.assertRaises(KeyboardInterrupt):
            self.worker.process(self.request(run="resume-001", mode="execute"), lambda ctx: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertEqual(self.worker.status()["runs"]["resume-001"]["status"], "interrupted")
        self.assertFalse((Path(self.cfg["state_dir"]) / "lease.json").exists())
        self.client.add_comment(SOURCE, f"[my-addness-worker:checkpoint run=resume-001 sha={HEAD} phase=review]")
        self.assertEqual(self.worker.process(self.request(run="resume-001", mode="execute"), lambda ctx: {"head": HEAD})["status"], "done")

        with self.assertRaises(KeyboardInterrupt):
            self.worker.process(self.request(run="resume-002", mode="execute"), lambda ctx: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.client.add_comment(SOURCE, f"[my-addness-worker:checkpoint run=resume-002 sha={HEAD2} phase=review]")
        self.assertEqual(self.worker.admit(self.request(run="resume-002", mode="execute")).reason, "resume head mismatch")

    def test_executor_failure_and_default_stub(self):
        for rid, executor in [("error-001", lambda ctx: 1 / 0), ("stub-001", None)]:
            result = self.worker.process(self.request(run=rid, mode="execute"), executor)
            self.assertEqual(result["status"], "failed")
            self.assertFalse((Path(self.cfg["state_dir"]) / "lease.json").exists())

    def test_inspect_writes_nothing(self):
        store_before = self.store_path.read_bytes()
        state = Path(self.cfg["state_dir"])
        self.assertFalse(state.exists())
        self.worker.inspect(self.request())
        self.assertEqual(store_before, self.store_path.read_bytes())
        self.assertFalse(state.exists())

    def test_default_intake_still_excludes_my_addness(self):
        self.assertEqual(HUB_DEFAULTS["addness"]["excluded_path_keywords"], ["My Addness"])
        g = {"id": "example-001", "title": "Claude task", "status": "NONE", "path": ["My Addness", "Task"], "comments": []}
        bridge = object.__new__(AddnessBridge)
        bridge.a = dict(HUB_DEFAULTS["addness"])
        bridge.a["title_prefix"] = "Claude"
        self.assertEqual(bridge.eligible(g), (False, "excluded path keyword 'My Addness'"))
        example = json.loads(Path("config/hub.config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(list(example["allowed_repos"]), ["alebeu1839-lab/ai-agent-hub"])
        self.assertEqual(example["addness"]["excluded_path_keywords"], ["My Addness"])


if __name__ == "__main__": unittest.main()
