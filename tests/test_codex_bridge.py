"""Codex MCP bridge: multi-line Japanese requests reach Codex intact and replies reach Claude.

Regression for 2026-11-21 (Addness 20f19eff): on Windows the prompt was passed as an argument
to codex.cmd, which drops everything after the first newline, and the bridge's stdio used
cp932, so Japanese requests were garbled and replies could fail to be written.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hub import codex_mcp_bridge as bridge

ROOT = Path(__file__).resolve().parent.parent
FAKES = ROOT / "tests" / "fakes"
BRIDGE = ROOT / "hub" / "codex_mcp_bridge.py"

REQUEST = ("docs/SETUP-CLAUDE-CODE.md の末尾に節を追加してください。\n"
           "\n"
           "1. Python 3.12 のパスを書く\n"
           "2. `claude mcp add codex -s local` の手順を書く\n"
           "最後の行：完了条件は “テストが通る” こと ✅")
REPLY = "実装しました。\n変更: docs/SETUP-CLAUDE-CODE.md\n確認: 読み返して一致 ✅ 🤖"
ENV_KEYS = ("CODEX_BIN", "CODEX_BRIDGE_WORKSPACE", "CODEX_BRIDGE_MAX_SANDBOX", "CODEX_BRIDGE_LOG",
            "FAKE_CODEX_RECORD", "FAKE_CODEX_REPLY", "FAKE_CODEX_MODE", "OPENAI_API_KEY",
            "CODEX_WINDOWS_REGISTERED_CORE")


class BridgeMultilineJapanese(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self._td = tempfile.TemporaryDirectory()
        self.ws = Path(self._td.name) / "ws"
        self.ws.mkdir()
        self.record = Path(self._td.name) / "record.json"
        os.environ.update({"CODEX_BIN": str(FAKES / "fake_codex.py"),
                           "CODEX_BRIDGE_WORKSPACE": str(self.ws),
                           "CODEX_BRIDGE_MAX_SANDBOX": "workspace-write",
                           "FAKE_CODEX_RECORD": str(self.record),
                           "FAKE_CODEX_REPLY": REPLY})
        bridge._PREFLIGHT = None

    def tearDown(self):
        bridge._PREFLIGHT = None
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def recorded(self) -> dict:
        return json.loads(self.record.read_text(encoding="utf-8"))

    def test_prompt_goes_via_stdin_complete(self):
        r = bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "codex_implement", "arguments": {"instructions": REQUEST}}})
        self.assertFalse(r["result"]["isError"], r)
        rec = self.recorded()
        self.assertEqual(rec["argv"][-1], "-")
        self.assertFalse(any("Task:" in a or "末尾" in a for a in rec["argv"]), rec["argv"])
        self.assertEqual(rec["prompt"], bridge.ROLE_PREFIX["codex_implement"] + REQUEST)
        self.assertIn(REPLY, r["result"]["content"][0]["text"])

    def test_registered_core_env_is_not_forwarded(self):
        os.environ["CODEX_WINDOWS_REGISTERED_CORE"] = "1"
        r = bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "codex_implement", "arguments": {"instructions": REQUEST}}})
        self.assertFalse(r["result"]["isError"], r)
        self.assertFalse(self.recorded()["codex_windows_registered_core_present"])

    def test_stdio_roundtrip_under_cp932(self):
        """Run the bridge as Claude Code does (pipes), forcing a cp932 default encoding."""
        env = {**os.environ, "PYTHONIOENCODING": "cp932", "PYTHONUTF8": "0"}
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "codex_implement", "arguments": {"instructions": REQUEST}}}]
        data = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in msgs).encode("utf-8")
        p = subprocess.run([sys.executable, str(BRIDGE)], input=data, capture_output=True,
                           env=env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        lines = [ln for ln in p.stdout.split(b"\n") if ln.strip()]
        resps = [json.loads(ln.decode("utf-8")) for ln in lines]  # stdout carries only JSON-RPC
        self.assertEqual([x["id"] for x in resps], [1, 2])
        res = resps[1]["result"]
        self.assertFalse(res["isError"], res)
        self.assertIn(REPLY, res["content"][0]["text"])
        self.assertEqual(self.recorded()["prompt"], bridge.ROLE_PREFIX["codex_implement"] + REQUEST)

    def test_stray_print_does_not_pollute_protocol(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]);"
                "from hub.codex_mcp_bridge import setup_stdio;"
                "proto = setup_stdio(); print('noise ログ'); proto.write('{\"ok\": \"✅\"}\\n'); proto.flush()")
        env = {**os.environ, "PYTHONIOENCODING": "cp932", "PYTHONUTF8": "0"}
        p = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(p.stdout, '{"ok": "✅"}\n'.encode("utf-8"))
        self.assertIn("noise ログ".encode("utf-8"), p.stderr)


if __name__ == "__main__":
    unittest.main()
