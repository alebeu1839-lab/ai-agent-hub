"""Owner/admin helpers.

    python -m hub.admin --config config/hub.config.json init-queue      # create the queue branch (pushes!)
    python -m hub.admin --config config/hub.config.json submit task.json
    python -m hub.admin --config config/hub.config.json pause  "reason"
    python -m hub.admin --config config/hub.config.json resume
    python -m hub.admin --config config/hub.config.json requeue <task-id>   # failed -> inbox (manual retry)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .config import load_config, validate_task, TaskRejected
from .gitutil import ensure_identity, git
from .queue import GitQueue, now_iso

QUEUE_README = """# Agent queue

This branch is the task queue for the AI Agent Hub runner. It contains data only.

- New task: add `queue/inbox/<id>.json` (see docs/GPT-INSTRUCTIONS.md on the code branch).
- Results: `queue/results/<id>/report.md` and `result.json`.
- Overview: `queue/status.md`.
- Emergency stop: create `queue/PAUSE`. Delete it to resume.
"""


def init_queue(cfg: dict) -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "q"
        git(["init", "--quiet", str(d)])
        ensure_identity(d)
        git(["checkout", "--quiet", "--orphan", cfg["queue_branch"]], d)
        q = d / cfg["queue_dir"]
        for s in ("inbox", "running", "done", "failed", "results"):
            (q / s).mkdir(parents=True)
            (q / s / ".gitkeep").write_text("")
        (d / "README.md").write_text(QUEUE_README, encoding="utf-8")
        git(["add", "-A"], d)
        git(["commit", "--quiet", "-m", "agent-hub: initialise task queue"], d)
        git(["remote", "add", "origin", cfg["queue_repo_url"]], d)
        exists = git(["ls-remote", "--heads", "origin", cfg["queue_branch"]], d).stdout.strip()
        if exists:
            print(f"queue branch {cfg['queue_branch']} already exists; nothing to do")
            return
        git(["push", "--quiet", "origin", f"HEAD:refs/heads/{cfg['queue_branch']}"], d)
        print(f"created queue branch {cfg['queue_branch']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hub.admin")
    ap.add_argument("--config", default="config/hub.config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-queue")
    s = sub.add_parser("submit"); s.add_argument("file")
    p = sub.add_parser("pause"); p.add_argument("reason", nargs="?", default="paused by owner")
    sub.add_parser("resume")
    r = sub.add_parser("requeue"); r.add_argument("task_id")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if a.cmd == "init-queue":
        init_queue(cfg)
        return 0
    q = GitQueue(cfg["queue_repo_url"], cfg["queue_branch"], Path(cfg["state_dir"]) / "admin-queue-repo",
                 cfg["queue_dir"])
    if a.cmd == "submit":
        t = json.loads(Path(a.file).read_text(encoding="utf-8"))
        t.setdefault("created_at", now_iso())
        try:
            validate_task(t, cfg)
        except TaskRejected as e:
            print(f"rejected locally: {e}", file=sys.stderr)
            return 2

        def fn():
            q._write(q.root / "inbox" / f"{t['id']}.json", t)
            return True
        q.transact(fn, f"task: {t['id']}")
    elif a.cmd == "pause":
        q.transact(lambda: (q.root / "PAUSE").write_text(a.reason + "\n") or True, "agent-hub: PAUSE")
    elif a.cmd == "resume":
        q.transact(lambda: ((q.root / "PAUSE").unlink(missing_ok=True), True)[1], "agent-hub: resume")
    elif a.cmd == "requeue":
        def fn():
            src = q.root / "failed" / f"{a.task_id}.json"
            if not src.exists():
                print("not in failed/", file=sys.stderr)
                return None
            t = q.read(src)
            t["_state"] = {"attempts": 0, "requeued_at": now_iso(),
                           "authorised": t.get("_state", {}).get("authorised")}
            q.move(a.task_id, "failed", "inbox", t)
            return True
        q.transact(fn, f"agent-hub: requeue {a.task_id}")
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
