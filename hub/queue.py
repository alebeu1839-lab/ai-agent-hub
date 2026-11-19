"""Git-backed task queue.

Layout on the queue branch (default ``agent-queue``)::

    queue/inbox/<id>.json      GPT writes new tasks here
    queue/running/<id>.json    claimed by a runner (lease)
    queue/done/<id>.json       finished OK
    queue/failed/<id>.json     rejected or gave up
    queue/results/<id>/        report.md, result.json, run.log  (GPT reads these)
    queue/status.md            human/GPT readable index
    queue/PAUSE                kill switch: if present, runners stop picking up work

Every state change is a commit + push. A rejected push means another runner moved
first, so we reset to the remote and retry the operation (claim = optimistic lock).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .gitutil import GitError, ensure_identity, git

STATES = ("inbox", "running", "done", "failed")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GitQueue:
    def __init__(self, repo_url: str, branch: str, local_dir: str | Path, qdir: str = "queue"):
        self.repo_url = repo_url
        self.branch = branch
        self.local = Path(local_dir)
        self.qdir = qdir

    # ---------- sync ----------
    @property
    def root(self) -> Path:
        return self.local / self.qdir

    def sync(self) -> None:
        if not (self.local / ".git").exists():
            self.local.parent.mkdir(parents=True, exist_ok=True)
            git(["clone", "--quiet", "--branch", self.branch, "--single-branch",
                 self.repo_url, str(self.local)])
            ensure_identity(self.local)
        git(["fetch", "--quiet", "origin", self.branch], self.local)
        git(["reset", "--quiet", "--hard", f"origin/{self.branch}"], self.local)
        git(["clean", "-fdq"], self.local)
        for s in STATES:
            (self.root / s).mkdir(parents=True, exist_ok=True)

    def _commit_push(self, message: str) -> bool:
        git(["add", "-A", self.qdir], self.local)
        if not git(["status", "--porcelain", self.qdir], self.local).stdout.strip():
            return True
        git(["commit", "--quiet", "-m", message], self.local)
        push = git(["push", "--quiet", "origin", f"HEAD:{self.branch}"], self.local, check=False)
        return push.returncode == 0

    def transact(self, fn, message: str, retries: int = 5):
        """Run fn() on a fresh checkout then push; retry on push races. fn returns result or None to abort."""
        last = None
        for attempt in range(retries):
            self.sync()
            result = fn()
            if result is None:
                return None
            if self._commit_push(message):
                return result
            last = f"push rejected (attempt {attempt + 1})"
            time.sleep(min(2 ** attempt, 10))
        raise GitError(last or "transaction failed")

    # ---------- queries ----------
    def paused(self) -> bool:
        return (self.root / "PAUSE").exists()

    def list(self, state: str) -> list[Path]:
        d = self.root / state
        return sorted(d.glob("*.json")) if d.exists() else []

    def read(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def last_commit_for(self, rel_path: str) -> str | None:
        out = git(["log", "--format=%H", "-1", "--", rel_path], self.local,
                  check=False).stdout.strip()
        return out or None

    # ---------- mutations (call inside transact) ----------
    def _write(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def move(self, task_id: str, src: str, dst: str, data: dict) -> None:
        srcp = self.root / src / f"{task_id}.json"
        if srcp.exists():
            srcp.unlink()
        self._write(self.root / dst / f"{task_id}.json", data)

    def write_results(self, task_id: str, files: dict[str, str]) -> None:
        d = self.root / "results" / task_id
        d.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (d / name).write_text(content, encoding="utf-8")

    def write_status_index(self) -> None:
        lines = ["# Agent queue status", "", f"_updated {now_iso()}_", "",
                 "| state | id | title | attempts | updated | result |",
                 "|---|---|---|---|---|---|"]
        for s in ("running", "inbox", "failed", "done"):
            for p in self.list(s):
                try:
                    t = self.read(p)
                except Exception:
                    t = {"id": p.stem}
                st = t.get("_state", {})
                res = f"results/{p.stem}/report.md" if (self.root / "results" / p.stem / "report.md").exists() else ""
                title = str(t.get("title", "")).replace("|", "/")[:60]
                lines.append(f"| {s} | {p.stem} | {title} | {st.get('attempts', 0)} | "
                             f"{st.get('updated_at', '')} | {res} |")
        if self.paused():
            lines.insert(2, "**PAUSED** (queue/PAUSE exists)\n")
        (self.root / "status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
