"""Isolated end-to-end tests: Addness (fake, local JSON) -> queue -> Claude Code -> Codex -> Addness.

No real Addness, GitHub, Claude or Codex account is used: local bare git repos stand in for
GitHub, tests/fakes/* for the CLIs, and FakeAddnessClient for Addness.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from hub import config as hubconfig
from hub.addness import AddnessAuthError, AddnessError, ClaudeMcpAddnessClient, FakeAddnessClient
from hub.addness_intake import AddnessBridge, CLAIM_RE, task_id_for
from hub.runner import Runner
from hub.handoff import select_next
from tests.test_runner import FAKES, Env, sh

PRACTICE = "fe511787-f4a2-460e-a100-3e0e4a775577"
MY_ADDNESS = "21c5ea2e-0714-4455-bb61-b9c23cf11a90"
DONE_G = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
STOPPED = "33333333-3333-4333-8333-333333333333"
PARENT = "AI社員運用基盤を作る（Addness × ChatGPT Work × Computer Use）"


def goal(gid, title, path_parent=PARENT, status="NONE", comments=None, body="READMEの1行を修正する。"):
    return {"id": gid, "title": title, "status": status, "owner": "owner-a", "ideal": "隔離ブランチで往復を1回成功させる",
            "path": ["２億を投資年利６％で回す", path_parent, title], "body": body,
            "comments": comments or []}


def seed_store(path: Path) -> None:
    goals = [
        goal(PRACTICE, "【Claude Code PC】隔離環境でAI開発往復を1件検証",
             comments=[{"author": "owner", "body": "【本人から実行指示】開始してよい", "created_at": "x"}]),
        goal(MY_ADDNESS, "【Claude Code PC】READMEの1行変更でClaude Code・Codex往復を検証",
             path_parent="My Addnessを個人利用で本家同等まで完成させる"),
        goal(DONE_G, "【Claude Code PC】終わったタスク", status="DONE"),
        goal(OTHER, "普通のタスク"),
        goal(STOPPED, "【Claude Code PC】止めたタスク",
             comments=[{"author": "owner", "body": "[ai-agent-hub:stop]", "created_at": "x"}]),
    ]
    path.write_text(json.dumps({"goals": {g["id"]: g for g in goals}}, ensure_ascii=False), encoding="utf-8")


class AddnessE2E(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        tmp = Path(self._td.name)
        self.env = Env(tmp)
        self.store = tmp / "addness.json"
        seed_store(self.store)
        self.env.cfg["addness"] = hubconfig._merge(hubconfig.DEFAULTS["addness"], {
            "enabled": True, "client": "fake", "fake_store": str(self.store),
            "target_repo": "owner/target", "base_branch": "main",
            "allowed_parent_titles": [PARENT], "excluded_goal_ids": [MY_ADDNESS]})
        os.environ["CLAUDE_BIN"] = str(FAKES / "fake_claude.py")
        os.environ["CODEX_BIN"] = str(FAKES / "fake_codex.py")
        for k in ("FAKE_CLAUDE_MODE", "FAKE_CODEX_MODE", "FAKE_CODEX_REVIEW", "FAKE_ADDNESS_FAIL",
                  "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k in ("FAKE_CLAUDE_MODE", "FAKE_CODEX_REVIEW", "FAKE_ADDNESS_FAIL"):
            os.environ.pop(k, None)
        self._td.cleanup()

    def bridge(self, runner_id=None, state=None):
        cfg = dict(self.env.cfg)
        if runner_id:
            cfg = {**cfg, "runner_id": runner_id, "state_dir": state or cfg["state_dir"]}
        return AddnessBridge(cfg), Runner(cfg)

    def goals(self):
        return json.loads(self.store.read_text(encoding="utf-8"))["goals"]

    def comments(self, gid):
        return [c["body"] for c in self.goals()[gid]["comments"]]

    # ------------------------------------------------------------------
    def test_full_round_trip_and_no_duplicates(self):
        b, r = self.bridge()
        out = b.cycle(r)
        self.assertEqual(out["status"], "ok", out)
        self.assertEqual(out["intake"], [PRACTICE])          # only the eligible task
        self.assertEqual(out["run"], "done")
        self.assertEqual(out["writeback"], [PRACTICE])
        tid = task_id_for(PRACTICE)
        self.assertTrue(self.env.exists(f"done/{tid}.json"))

        g = self.goals()[PRACTICE]
        body = g["body"]
        self.assertIn("AI Agent Hub 実行結果（完了報告）", body)
        self.assertIn("レビュー判定（Claude Code）: **PASS**", body)
        self.assertIn("codex_implement:ok", body)
        head = sh("git", "--git-dir", str(self.env.bare), "rev-parse", f"agent/{tid}").strip()
        self.assertIn(f"コミットSHA: `{head}`", body)       # SHA written back matches the pushed branch
        cs = self.comments(PRACTICE)
        self.assertEqual(sum(1 for c in cs if c.startswith("[ai-agent-hub:claim")), 1)
        self.assertEqual(sum(1 for c in cs if c.startswith("[ai-agent-hub:done")), 1)
        self.assertIn(f"sha={head}", cs[-1])

        # excluded / ineligible tasks untouched
        for gid in (MY_ADDNESS, DONE_G, OTHER, STOPPED):
            self.assertFalse(any("ai-agent-hub:claim" in c for c in self.comments(gid)), gid)

        # main untouched
        self.assertNotIn("CODEX_WAS_HERE.md",
                         sh("git", "--git-dir", str(self.env.bare), "ls-tree", "--name-only", "main"))

        # second cycle and a "restarted" process: nothing new is claimed, run or written
        out2 = b.cycle(r)
        self.assertEqual((out2["intake"], out2["run"], out2["writeback"]), ([], "idle", []))
        b3, r3 = self.bridge()  # fresh objects = after PC reboot, same state dir
        out3 = b3.cycle(r3)
        self.assertEqual((out3["intake"], out3["run"], out3["writeback"]), ([], "idle", []))
        self.assertEqual(len(self.comments(PRACTICE)), len(cs))

    def test_review_rejects_then_codex_fixes(self):
        os.environ["FAKE_CODEX_REVIEW"] = "reject_once"
        b, r = self.bridge()
        out = b.cycle(r)
        self.assertEqual(out["run"], "done")
        report = self.env.read_queue(f"results/{task_id_for(PRACTICE)}/report.md")
        self.assertIn("round 1: changes requested -> re-delegated", report)
        self.assertIn("round 2: approved", report)
        result = json.loads(self.env.read_queue(f"results/{task_id_for(PRACTICE)}/result.json"))
        tools = [c["tool"] for c in result["codex_calls"]]
        self.assertEqual(tools, ["codex_implement", "codex_review", "codex_implement", "codex_review"])
        self.assertIn("**PASS**", self.goals()[PRACTICE]["body"])

    def test_other_pc_sees_claim_marker(self):
        b, _ = self.bridge()
        self.assertEqual(b.intake(), [PRACTICE])
        other = Path(self._td.name) / "state-pc2"
        b2, _ = self.bridge("pc-2", str(other))
        self.assertEqual(b2.intake(), [])               # different PC, empty ledger, still no duplicate
        self.assertEqual(b2.ledger.get(PRACTICE)["reason"], "already claimed")

    def test_claim_race_earliest_wins(self):
        b, _ = self.bridge()
        real = b.client.add_comment

        def racing(gid, body):  # another PC writes its claim just before ours
            if body.startswith("[ai-agent-hub:claim"):
                real(gid, f"[ai-agent-hub:claim task={task_id_for(gid)} runner=pc-2 nonce=abc123]")
            real(gid, body)
        b.client.add_comment = racing
        self.assertEqual(b.intake(), [])
        self.assertEqual(b.ledger.get(PRACTICE)["state"], "lost")
        self.assertFalse(self.env.exists(f"inbox/{task_id_for(PRACTICE)}.json"))

    def test_crash_after_claim_is_resumed_once(self):
        b, _ = self.bridge()
        b._submit = lambda g: (_ for _ in ()).throw(OSError("power cut"))
        with self.assertRaises(OSError):
            b.intake()
        # ledger may say claimed; also simulate the ledger write being lost entirely
        (Path(self.env.cfg["state_dir"]) / "addness" / "ledger.json").unlink(missing_ok=True)
        b2, r2 = self.bridge()
        out = b2.cycle(r2)
        self.assertEqual(out["intake"], [PRACTICE])
        self.assertEqual(out["run"], "done")
        claims = [c for c in self.comments(PRACTICE) if CLAIM_RE.search(c)]
        self.assertEqual(len(claims), 1)

    def test_addness_auth_expiry_blocks_then_resumes(self):
        os.environ["FAKE_ADDNESS_FAIL"] = "auth"
        b, r = self.bridge()
        out = b.cycle(r)
        self.assertEqual(out["status"], "blocked: addness auth")
        status = self.env.read_queue("addness_intake_status.md")   # visible to GPT without Addness
        self.assertIn("blocked: addness auth", status)
        self.assertIn("re-authenticate", status)
        os.environ.pop("FAKE_ADDNESS_FAIL")
        out = b.cycle(r)
        self.assertEqual((out["status"], out["run"]), ("ok", "done"))
        self.assertIn("status:** ok", self.env.read_queue("addness_intake_status.md"))

    def test_writeback_retried_after_outage(self):
        b, r = self.bridge()
        b.intake()
        self.assertEqual(r.run_once(), "done")
        os.environ["FAKE_ADDNESS_FAIL"] = "network"
        self.assertEqual(b.cycle(r)["status"], "error: addness")
        os.environ.pop("FAKE_ADDNESS_FAIL")
        self.assertEqual(b.cycle(r)["writeback"], [PRACTICE])
        self.assertEqual(sum(1 for c in self.comments(PRACTICE) if c.startswith("[ai-agent-hub:done")), 1)

    def test_pause_stops_everything(self):
        b, r = self.bridge()
        (Path(self.env.cfg["state_dir"]) / "PAUSE").write_text("owner stop")
        self.assertEqual(b.cycle(r)["status"], "paused")
        self.assertFalse(any("claim" in c for c in self.comments(PRACTICE)))
        (Path(self.env.cfg["state_dir"]) / "PAUSE").unlink()
        self.assertEqual(b.cycle(r)["run"], "done")

    def test_failed_run_is_written_back_as_waiting(self):
        os.environ["FAKE_CLAUDE_MODE"] = "crash"
        b, r = self.bridge()
        out = b.cycle(r)
        self.assertEqual(out["run"], "failed")
        body = self.goals()[PRACTICE]["body"]
        self.assertIn("確認待ち", body)
        self.assertIn("キュー状態: `failed`", body)
        self.assertIn("status=failed", self.comments(PRACTICE)[-1])

    def test_owner_allowlist(self):
        self.env.cfg["addness"]["allowed_owner_names"] = ["someone-else"]
        b, _ = self.bridge()
        self.assertEqual(b.intake(), [])
        self.env.cfg["addness"]["allowed_owner_names"] = ["owner-a"]
        b, _ = self.bridge()
        self.assertEqual(b.intake(), [PRACTICE])

    def test_second_cycle_while_locked_does_nothing(self):
        b, r = self.bridge()
        lock = Path(self.env.cfg["state_dir"]) / "addness" / "cycle.lock"
        lock.write_text("999 running")
        self.assertTrue(b.cycle(r)["status"].startswith("locked"))
        os.utime(lock, (0, 0))  # stale lock from a crashed process expires
        self.assertEqual(b.cycle(r)["status"], "ok")


class HandoffWriteback(unittest.TestCase):
    def run_writeback(self, with_sibling=True):
        self._td = tempfile.TemporaryDirectory()
        tmp = Path(self._td.name)
        store = tmp / "addness.json"
        task_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        parent_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        next_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        task = goal(task_id, "completed task")
        task["parent_id"] = parent_id
        goals = {task_id: task, parent_id: goal(parent_id, "parent")}
        kids = [{"id": task_id, "title": task["title"], "status": "NONE"}]
        if with_sibling:
            goals[next_id] = goal(next_id, "follow up")
            kids.append({"id": next_id, "title": goals[next_id]["title"], "status": "NONE"})
        store.write_text(json.dumps({"goals": goals, "children": {parent_id: kids, task_id: []},
                                     "today": []}, ensure_ascii=False), encoding="utf-8")
        client = FakeAddnessClient(store)
        state_dir = tmp / "state"
        queue = _WritebackQueue(tmp / "queue")
        tid = task_id_for(task_id)
        (queue.root / "done").mkdir(parents=True)
        (queue.root / "done" / f"{tid}.json").write_text("{}", encoding="utf-8")
        result_dir = queue.root / "results" / tid
        result_dir.mkdir(parents=True)
        (result_dir / "result.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")
        (result_dir / "report.md").write_text("## Review verdict\nPASS\n", encoding="utf-8")
        cfg = {"state_dir": str(state_dir), "runner_id": "test", "queue_repo_url": "",
               "queue_branch": "agent-queue", "queue_dir": "queue",
               "addness": {"handoff": {"enabled": True}}}
        bridge = AddnessBridge(cfg, client=client, queue=queue)
        bridge.ledger.set(task_id, state="submitted", task_id=tid)
        return bridge, client, store, task_id, next_id

    def test_writeback_adds_one_today_todo_once(self):
        bridge, client, store, task_id, next_id = self.run_writeback()
        calls = []
        add_today = client.add_today_todo
        client.add_today_todo = lambda goal_id: (calls.append(goal_id), add_today(goal_id))[-1]
        self.assertEqual(bridge.writeback(), [task_id])
        self.assertEqual(client.list_today_ids(), {next_id})
        ledger = bridge.ledger.get(task_id)
        self.assertEqual(ledger["handoff_added"], next_id)
        self.assertEqual(calls, [next_id])
        # Force another write-back pass after removing the todo to exercise the ledger guard itself.
        saved = client._load()
        saved["today"] = []
        client._save(saved)
        bridge.ledger.set(task_id, state="submitted", task_id=task_id_for(task_id), detail_written=True)
        self.assertEqual(bridge.writeback(), [task_id])
        self.assertEqual(calls, [next_id])
        self.assertEqual(client.list_today_ids(), set())
        detail = client.get_task(task_id)["body"]
        self.assertIn("## 残件と次の1件", detail)
        self.assertIn(next_id, detail)
        self._td.cleanup()

    def test_fake_children_metadata_is_enriched_and_deleted_child_is_marked(self):
        bridge, client, _, task_id, next_id = self.run_writeback()
        parent_id = client.get_task(task_id)["parent_id"]
        data = client._load()
        deleted_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        data["children"][parent_id].append({"id": deleted_id, "title": "deleted", "status": "NONE"})
        client._save(data)
        stored_child = client._load()["children"][parent_id][1]
        self.assertEqual(set(stored_child), {"id", "title", "status"})
        children = client.list_children(parent_id)
        self.assertEqual(set(children[1]) - {"owner", "ideal", "path"},
                         {"id", "title", "status", "body", "comments", "ai_activity"})
        self.assertIn("body", children[1])
        self.assertTrue(children[-1]["deleted"])
        selection = select_next({"id": parent_id}, children[1:], set(), set(), {})
        self.assertIn((deleted_id, "deleted"), selection.skipped)
        self._td.cleanup()

    def test_handoff_error_keeps_main_writeback_and_auth_error_propagates(self):
        bridge, client, _, task_id, _ = self.run_writeback()

        def fail_handoff(_gid):
            raise RuntimeError("temporary handoff lookup failure")

        bridge._handoff_writeback = fail_handoff
        self.assertEqual(bridge.writeback(), [task_id])
        self.assertIn("AI Agent Hub 実行結果", client.get_task(task_id)["body"])
        self.assertIn("引継ぎ処理エラー", client.get_task(task_id)["body"])

        bridge.ledger.set(task_id, state="submitted", task_id=task_id_for(task_id), detail_written=False)
        bridge._handoff_writeback = lambda _gid: (_ for _ in ()).throw(AddnessAuthError("auth required"))
        with self.assertRaises(AddnessAuthError):
            bridge.writeback()
        self._td.cleanup()

    def test_no_child_does_not_call_add_today_todo(self):
        from unittest.mock import patch
        bridge, client, _, task_id, _ = self.run_writeback(with_sibling=False)
        with patch.object(client, "add_today_todo", wraps=client.add_today_todo) as add:
            bridge._handoff_writeback(task_id)
            add.assert_not_called()
        self._td.cleanup()


class _WritebackQueue:
    def __init__(self, root):
        self.root = root
        self.root.mkdir(parents=True)

    def sync(self):
        pass

    def list(self, state):
        directory = self.root / state
        return sorted(directory.glob("*.json")) if directory.exists() else []


class ClaudeMcpClientParsing(unittest.TestCase):
    """The real client's answer parsing and auth detection, using a fake `claude`."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.fake = self.tmp / "fake_claude_addness.py"
        self.fake.write_text(
            "import json,os,sys\nargs=sys.argv[1:]\nsys.stdin.read()\n"
            "assert '--tools' in args and args[args.index('--tools')+1]==''\n"
            "assert all(t.startswith('mcp__addness__') for t in args[args.index('--allowedTools')+1].split(','))\n"
            "print(os.environ['FAKE_OUT'])\nsys.exit(int(os.environ.get('FAKE_RC','0')))\n")
        os.environ["CLAUDE_BIN"] = str(self.fake)
        cfg = hubconfig._merge(hubconfig.DEFAULTS, {"state_dir": str(self.tmp)})
        self.client = ClaudeMcpAddnessClient(cfg, self.tmp)

    def tearDown(self):
        for k in ("FAKE_OUT", "FAKE_RC", "CLAUDE_BIN"):
            os.environ.pop(k, None)
        self._td.cleanup()

    def answer(self, payload: dict, rc=0):
        os.environ["FAKE_OUT"] = json.dumps({"result": f"<<<JSON {json.dumps(payload)} JSON>>>"})
        os.environ["FAKE_RC"] = str(rc)

    def test_search_filters_bad_ids(self):
        self.answer({"items": [{"id": PRACTICE, "title": "【Claude Code PC】x", "status": "NONE"},
                               {"id": "not-a-uuid", "title": "【Claude Code PC】y"}]})
        self.assertEqual([i["id"] for i in self.client.search_tasks("【Claude Code PC】")], [PRACTICE])

    def test_auth_error_detected(self):
        self.answer({"error": "Addness MCP needs authentication", "auth": True})
        with self.assertRaises(AddnessAuthError):
            self.client.search_tasks("x")
        os.environ["FAKE_OUT"] = "Error: MCP server addness: 401 Unauthorized"
        os.environ["FAKE_RC"] = "1"
        with self.assertRaises(AddnessAuthError):
            self.client.get_task(PRACTICE)

    def test_mismatched_goal_rejected(self):
        self.answer({"id": OTHER, "title": "t"})
        with self.assertRaises(Exception):
            self.client.get_task(PRACTICE)

    def test_list_children_fetches_details_in_a_second_stage_and_marks_deleted(self):
        from unittest.mock import patch
        child_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        deleted_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        parent_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        with patch.object(self.client, "_call", side_effect=[
                {"children": [{"id": child_id, "title": "child", "status": "NONE"},
                              {"id": deleted_id, "title": "gone", "status": "NONE"},
                              {"id": "bad-id", "title": "invalid", "status": "NONE"}]},
                {"body": "detail body", "comments": [{"body": "comment"}], "ai_activity": "working"},
                AddnessError("goal not found: deleted")]) as call:
            children = self.client.list_children(parent_id)
        self.assertEqual(children[0]["body"], "detail body")
        self.assertEqual(children[0]["comments"], [{"body": "comment"}])
        self.assertEqual(children[0]["ai_activity"], "working")
        self.assertTrue(children[1]["deleted"])
        self.assertTrue(children[2]["invalid_id"])
        self.assertEqual(call.call_count, 3)  # children list + two valid UUID detail lookups
        self.assertTrue(call.call_args_list[0].args[1].find('sections=["children"]') >= 0)
        self.assertTrue(call.call_args_list[1].args[1].find('sections=["body","comments"]') >= 0)

    def test_create_today_todo_uses_objective_id_and_validates_uuid(self):
        from unittest.mock import patch
        objective_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        with patch.object(self.client, "_call", return_value={"ok": True}) as call:
            self.client.add_today_todo(objective_id)
            self.assertIn(f'objective_id="{objective_id}"', call.call_args.args[1])
            self.assertEqual(call.call_args.args[0], ["create_today_todo"])
            with self.assertRaises(AddnessError):
                self.client.add_today_todo("not-a-uuid")
            self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
