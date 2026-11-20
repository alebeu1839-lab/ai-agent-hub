#!/usr/bin/env python3
"""Isolated end-to-end demonstration with an evidence log (no real Addness/GitHub/Claude/Codex).

    python scripts/e2e_isolated.py [--out evidence.md]

Builds a throwaway bare git repo (stands in for GitHub: `main` + `agent-queue`), a fake Addness
store seeded like the real tree (practice task, a My Addness task that must be ignored, a
completed task, a stopped task), and runs the real hub code with tests/fakes/* in place of the
`claude` and `codex` CLIs. Prints each step and the final Addness writeback.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import config as hubconfig  # noqa: E402
from hub.addness_intake import AddnessBridge, task_id_for  # noqa: E402
from hub.runner import Runner  # noqa: E402
from tests.test_addness_intake import MY_ADDNESS, PARENT, PRACTICE, seed_store  # noqa: E402
from tests.test_runner import FAKES, Env, sh  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    log: list[str] = []

    def say(s=""):
        print(s)
        log.append(s)

    tmp = Path(tempfile.mkdtemp(prefix="hub-e2e-"))
    try:
        env = Env(tmp)
        store = tmp / "addness.json"
        seed_store(store)
        env.cfg["addness"] = hubconfig._merge(hubconfig.DEFAULTS["addness"], {
            "enabled": True, "client": "fake", "fake_store": str(store), "target_repo": "owner/target",
            "base_branch": "main", "allowed_parent_titles": [PARENT], "excluded_goal_ids": [MY_ADDNESS]})
        os.environ["CLAUDE_BIN"] = str(FAKES / "fake_claude.py")
        os.environ["CODEX_BIN"] = str(FAKES / "fake_codex.py")
        os.environ["FAKE_CODEX_REVIEW"] = "reject_once"  # first review fails -> Claude sends it back
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FAKE_ADDNESS_FAIL", "FAKE_CLAUDE_MODE"):
            os.environ.pop(k, None)
        goals = lambda: json.loads(store.read_text(encoding="utf-8"))["goals"]  # noqa: E731

        say("# Isolated E2E: Addness -> Claude Code -> Codex -> review -> Addness")
        say(f"- sandbox: {tmp} (deleted afterwards)")
        say("\n## 1. Addness auth expired (owner must re-login)")
        os.environ["FAKE_ADDNESS_FAIL"] = "auth"
        b, r = AddnessBridge(env.cfg), Runner(env.cfg)
        say(f"- cycle -> {b.cycle(r)}")
        say("- queue/addness_intake_status.md:\n```\n" + env.read_queue("addness_intake_status.md").strip() + "\n```")
        os.environ.pop("FAKE_ADDNESS_FAIL")

        say("\n## 2. Login restored: one cycle picks up the task without any button press")
        out = b.cycle(r)
        say(f"- cycle -> {json.dumps(out, ensure_ascii=False)}")
        tid = task_id_for(PRACTICE)
        res = json.loads(env.read_queue(f"results/{tid}/result.json"))
        say("- Codex calls (Claude -> Codex -> Claude): " + ", ".join(
            f"{c['tool']}:{'ok' if c['exit_code'] == 0 else c['error_kind']}" for c in res["codex_calls"]))
        rep = env.read_queue(f"results/{tid}/report.md")
        verdict = rep[rep.index("## Review verdict"):].split("## Needs")[0].strip()
        say("- review gate:\n```\n" + verdict + "\n```")
        head = sh("git", "--git-dir", str(env.bare), "rev-parse", f"agent/{tid}").strip()
        say(f"- work branch agent/{tid} @ {head}")
        say("- files on work branch: " + sh("git", "--git-dir", str(env.bare), "ls-tree", "--name-only",
                                            f"agent/{tid}").replace("\n", " "))
        say("- files on main (unchanged): " + sh("git", "--git-dir", str(env.bare), "ls-tree", "--name-only",
                                                 "main").replace("\n", " "))

        say("\n## 3. Written back to the same Addness task")
        g = goals()[PRACTICE]
        say("```\n" + g["body"][g["body"].index("### "):].strip() + "\n```")
        say("- comments:")
        for c in g["comments"]:
            say(f"  - {c['body'].splitlines()[0]}")
        others = {gid: [c["body"][:30] for c in x["comments"]] for gid, x in goals().items() if gid != PRACTICE}
        say(f"- other tasks' comments (must be no ai-agent-hub markers): {json.dumps(others, ensure_ascii=False)}")

        say("\n## 4. Reboot / repeated runs: no duplicate pickup")
        b2, r2 = AddnessBridge(env.cfg), Runner(env.cfg)
        say(f"- fresh process cycle -> {b2.cycle(r2)}")
        pc2 = dict(env.cfg, runner_id="pc-2", state_dir=str(tmp / "state-pc2"))
        say(f"- a second PC with an empty ledger -> {AddnessBridge(pc2).cycle(Runner(pc2))}")
        n_claim = sum(c["body"].startswith("[ai-agent-hub:claim") for c in goals()[PRACTICE]["comments"])
        n_done = sum(c["body"].startswith("[ai-agent-hub:done") for c in goals()[PRACTICE]["comments"])
        say(f"- claim markers: {n_claim}, done markers: {n_done}")
        ok = n_claim == 1 and n_done == 1 and "**PASS**" in g["body"] and head in g["body"]
        say(f"\n**RESULT: {'PASS' if ok else 'FAIL'}**")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.out:
        Path(a.out).write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
