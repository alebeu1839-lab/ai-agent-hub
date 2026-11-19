"""AI Agent Hub runner: queue (GitHub) -> Claude Code -> Codex (MCP) -> results (GitHub).

Usage:
    python -m hub.runner --config config/hub.config.json once     # process at most one task
    python -m hub.runner --config config/hub.config.json loop     # poll forever (Ctrl+C to stop)
    python -m hub.runner --config config/hub.config.json status   # print queue status

Safety summary (details in docs/ARCHITECTURE.md):
  * tasks are data validated against an allowlist (repo, base branch, mode, size)
  * optional: the commit that added the task must be GitHub-verified and authored by an
    allowed submitter (the owner's account used by the ChatGPT GitHub connector)
  * Claude runs with an explicit tool allowlist; Codex is capped by sandbox mode
  * only the runner pushes, and only to ``agent/<task-id>``; protected branches are refused
  * queue/PAUSE stops all processing; usage-limit errors trigger a cooldown
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import claude_exec
from .config import TaskRejected, branch_matches, load_config, validate_task
from .gitutil import GitError, ensure_identity, git
from .queue import GitQueue, now_iso
from .redact import redact

log = logging.getLogger("hub")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso_in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh_verify_submitter(repo_slug: str, sha: str, allowed: list[str],
                        require_signed: bool = False) -> tuple[bool, str]:
    """Ask the GitHub API who authored the commit that submitted a task.

    The author login must be in ``allowed``. Commits made through the GitHub API by
    connectors (tested: GitHub MCP / app tokens) are *unsigned*, so a signature is only
    required when ``require_signed`` is set.
    """
    if not shutil.which("gh"):
        return False, "gh CLI not available to verify submitter (fail closed)"
    proc = subprocess.run(["gh", "api", f"repos/{repo_slug}/commits/{sha}",
                           "--jq", "{login: .author.login, verified: .commit.verification.verified}"],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return False, f"could not query commit {sha[:10]}: {redact(proc.stderr.strip())[:200]}"
    info = json.loads(proc.stdout or "{}")
    if info.get("login") not in allowed:
        return False, f"commit author {info.get('login')!r} is not an allowed submitter"
    if require_signed and not info.get("verified"):
        return False, f"commit {sha[:10]} is not signed/verified"
    return True, f"commit by {info.get('login')} (signed={bool(info.get('verified'))})"


def repo_slug_from_url(url: str) -> str | None:
    u = url.rstrip("/").removesuffix(".git")
    if "github.com" not in u:
        return None
    return "/".join(u.replace(":", "/").split("/")[-2:])


class Runner:
    def __init__(self, cfg: dict, verifier=None):
        self.cfg = cfg
        self.state = Path(cfg["state_dir"])
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "logs").mkdir(exist_ok=True)
        self.queue = GitQueue(cfg["queue_repo_url"], cfg["queue_branch"], self.state / "queue-repo",
                              cfg["queue_dir"])
        self.verifier = verifier or gh_verify_submitter
        self.me = cfg["runner_id"]

    # ---------- bookkeeping ----------
    def history(self, event: str, **kw) -> None:
        entry = {"ts": now_iso(), "runner": self.me, "event": event, **kw}
        with open(self.state / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(redact(json.dumps(entry, ensure_ascii=False)) + "\n")
        log.info("%s %s", event, redact(json.dumps(kw, ensure_ascii=False))[:500])

    def cooldown_until(self) -> datetime | None:
        p = self.state / "cooldown_until"
        return _parse_iso(p.read_text().strip()) if p.exists() else None

    def set_cooldown(self, seconds: int, reason: str) -> None:
        (self.state / "cooldown_until").write_text(_iso_in(seconds))
        self.history("cooldown", seconds=seconds, reason=reason)

    # ---------- selection ----------
    def _authorise(self, path: Path) -> tuple[bool, str]:
        sec = self.cfg["security"]
        if not sec.get("verify_submitter"):
            return True, "submitter verification disabled in config"
        rel = f"{self.cfg['queue_dir']}/inbox/{path.name}"
        sha = self.queue.last_commit_for(rel)
        slug = repo_slug_from_url(self.cfg["queue_repo_url"])
        if not sha or not slug:
            return False, "cannot determine the commit/repo that submitted this task"
        return self.verifier(slug, sha, sec.get("allowed_submitters", []),
                             require_signed=bool(sec.get("require_signed_commit")))

    def pick(self) -> tuple[str, dict] | None:
        """Return (kind, task) where kind is 'resume' or 'new'."""
        # 1) our own interrupted tasks first (crash / reboot recovery)
        for p in self.queue.list("running"):
            t = self.queue.read(p)
            if t.get("_state", {}).get("runner") == self.me:
                return "resume", t
        # 2) new tasks in priority order whose backoff has expired
        now = datetime.now(timezone.utc)
        cands = []
        for p in self.queue.list("inbox"):
            try:
                t = self.queue.read(p)
            except json.JSONDecodeError as e:
                self.reject(p.stem, {"id": p.stem}, f"invalid JSON: {e}")
                continue
            nb = _parse_iso(t.get("_state", {}).get("not_before"))
            if nb and nb > now:
                continue
            cands.append((-int(t.get("priority", 0) or 0), str(t.get("created_at", "")), p, t))
        for _, _, p, t in sorted(cands, key=lambda c: c[:2]):
            if p.stem != t.get("id"):
                self.reject(p.stem, t, "file name must equal task id")
                continue
            if not t.get("_state", {}).get("authorised"):
                ok, why = self._authorise(p)
                if not ok:
                    self.reject(p.stem, t, f"unauthorised: {why}")
                    continue
                t.setdefault("_state", {})["authorised"] = why
            try:
                validate_task(t, self.cfg)
            except TaskRejected as e:
                self.reject(p.stem, t, f"invalid task: {e}")
                continue
            return "new", t
        return None

    def reject(self, tid: str, task: dict, reason: str) -> None:
        task = dict(task)
        task["_state"] = {**task.get("_state", {}), "status": "rejected", "error": reason,
                          "updated_at": now_iso()}

        def fn():
            if not (self.queue.root / "inbox" / f"{tid}.json").exists():
                return None
            self.queue.move(tid, "inbox", "failed", task)
            self.queue.write_results(tid, {"report.md": f"# Task {tid}: REJECTED\n\n{reason}\n",
                                           "result.json": json.dumps({"id": tid, "status": "rejected",
                                                                      "error": reason}, indent=2)})
            self.queue.write_status_index()
            return True
        self.queue.transact(fn, f"agent-hub: reject {tid}")
        self.history("rejected", task=tid, reason=reason)

    # ---------- execution ----------
    def claim(self, task: dict) -> dict | None:
        tid = task["id"]
        st = task.get("_state", {})
        new_state = {**st, "status": "running", "runner": self.me, "claimed_at": now_iso(),
                     "updated_at": now_iso(), "attempts": int(st.get("attempts", 0)) + 1}
        claimed = {**task, "_state": new_state}

        def fn():
            if not (self.queue.root / "inbox" / f"{tid}.json").exists():
                return None  # someone else took it
            self.queue.move(tid, "inbox", "running", claimed)
            self.queue.write_status_index()
            return claimed
        res = self.queue.transact(fn, f"agent-hub: claim {tid} by {self.me}")
        if res:
            self.history("claimed", task=tid, attempt=new_state["attempts"])
        return res

    def prepare_workspace(self, t: dict) -> Path:
        repo_cfg = self.cfg["allowed_repos"][t["repo"]]
        ws = self.state / "work" / t["id"]
        wb = t["work_branch"]
        if branch_matches(wb, self.cfg["protected_branches"]):
            raise TaskRejected("refusing protected work branch")
        if (ws / ".git").exists():
            cur = git(["rev-parse", "--abbrev-ref", "HEAD"], ws).stdout.strip()
            if cur == wb:
                return ws  # keep in-progress work (resume)
            shutil.rmtree(ws)
        ws.parent.mkdir(parents=True, exist_ok=True)
        git(["clone", "--quiet", repo_cfg["clone_url"], str(ws)], timeout=900)
        ensure_identity(ws)
        remote_has_wb = git(["ls-remote", "--heads", "origin", wb], ws).stdout.strip()
        if remote_has_wb:  # progress pushed by an earlier attempt
            git(["checkout", "--quiet", "-B", wb, f"origin/{wb}"], ws)
        else:
            git(["checkout", "--quiet", "-B", wb, f"origin/{t['base_branch']}"], ws)
        return ws

    def checkpoint(self, t: dict, ws: Path, message: str) -> dict:
        """Commit worktree changes and push the work branch. Returns git info for the report."""
        info = {"work_branch": t["work_branch"], "committed": False, "pushed": False}
        git(["add", "-A"], ws)
        if git(["status", "--porcelain"], ws).stdout.strip():
            git(["commit", "--quiet", "-m", message], ws)
            info["committed"] = True
        base = f"origin/{t['base_branch']}"
        info["commits_ahead"] = int(git(["rev-list", "--count", f"{base}..HEAD"], ws).stdout.strip() or 0)
        info["diffstat"] = git(["diff", "--stat", f"{base}...HEAD"], ws).stdout.strip()[-3000:]
        info["head"] = git(["rev-parse", "HEAD"], ws).stdout.strip()
        if self.cfg["push_work_branch"] and info["commits_ahead"] > 0:
            wb = t["work_branch"]
            if branch_matches(wb, self.cfg["protected_branches"]) or not wb.startswith(self.cfg["work_branch_prefix"]):
                raise GitError(f"refusing to push {wb}")
            p = git(["push", "--quiet", "origin", f"HEAD:refs/heads/{wb}"], ws, check=False, timeout=600)
            info["pushed"] = p.returncode == 0
            if p.returncode != 0:
                info["push_error"] = redact(p.stderr.strip())[:500]
        return info

    def process(self, kind: str, task: dict) -> str:
        if kind == "new":
            task = self.claim(task)
            if task is None:
                return "lost-claim"
        else:
            self.history("resuming", task=task["id"])
        t = validate_task(task, self.cfg)
        tid = t["id"]
        st = dict(task.get("_state", {}))
        run_dir = self.state / "runs" / tid / f"attempt-{st.get('attempts', 1)}"
        started = time.time()

        try:
            ws = self.prepare_workspace(t)
        except (GitError, subprocess.TimeoutExpired) as e:
            return self.finish(t, st, None, {"error": f"workspace setup failed: {e}"}, "transient", run_dir, started)

        resume_sid = st.get("session_id") if kind == "resume" or st.get("resume") else None
        self.history("claude_start", task=tid, resume_session=bool(resume_sid))
        result = claude_exec.run_claude(t, ws, self.cfg, run_dir, resume_session=resume_sid)
        if resume_sid and not result.ok and "session" in (result.stderr_tail + result.text).lower():
            result = claude_exec.run_claude(t, ws, self.cfg, run_dir, resume_session=None)
        if result.session_id:
            st["session_id"] = result.session_id

        try:
            msg = f"agent({tid}): {'result' if result.ok else 'checkpoint'} attempt {st.get('attempts', 1)}"
            gitinfo = self.checkpoint(t, ws, msg)
        except GitError as e:
            gitinfo = {"error": str(e)}
        return self.finish(t, st, result, gitinfo, None if result.ok else result.error_kind, run_dir, started)

    def finish(self, t: dict, st: dict, result, gitinfo: dict, error_kind: str | None,
               run_dir: Path, started: float) -> str:
        tid = t["id"]
        entries = []
        cpath = run_dir / "codex_calls.jsonl"
        if cpath.exists():
            entries = [json.loads(l) for l in cpath.read_text(encoding="utf-8").splitlines() if l.strip()]
        codex_calls = [e for e in entries if e.get("event") != "started"]
        started_n = sum(1 for e in entries if e.get("event") == "started")
        unfinished = max(0, started_n - sum(1 for c in codex_calls if c.get("exit_code") is not None))
        warnings = []
        if unfinished:
            warnings.append(f"{unfinished} Codex call(s) started but never returned (timeout/cancelled)")
        failed_calls = [c for c in codex_calls if c.get("exit_code") != 0]
        if failed_calls:
            kinds = sorted({str(c.get("error_kind")) for c in failed_calls})
            warnings.append(f"{len(failed_calls)} Codex call(s) failed: {', '.join(kinds)}")
        if result is not None and result.ok and t["mode"] == "implement" and \
                not any(c.get("exit_code") == 0 for c in codex_calls):
            warnings.append("no successful Codex call: work was done by Claude alone or not at all")
        if result is not None and result.raw.get("permission_denials"):
            warnings.append(f"{len(result.raw['permission_denials'])} tool call(s) denied by the runner allowlist")

        retry = self.cfg["retry"]
        attempts = int(st.get("attempts", 1))
        if error_kind is None:
            status, dst = "done", "done"
        elif error_kind in ("transient", "usage_limit", "timeout") and attempts < retry["max_attempts"]:
            status, dst = "retry_scheduled", "inbox"
            backoff = min(retry["base_backoff_sec"] * 2 ** (attempts - 1), retry["max_backoff_sec"])
            if error_kind == "usage_limit":
                backoff = max(backoff, retry["usage_limit_cooldown_sec"])
                self.set_cooldown(retry["usage_limit_cooldown_sec"], f"usage limit on {tid}")
            st["not_before"] = _iso_in(backoff)
            st["resume"] = True
        else:
            status, dst = "failed", "failed"

        err = None
        if result is not None and not result.ok:
            err = f"{error_kind}: exit {result.exit_code}; {result.stderr_tail[-600:] or result.text[-600:]}"
        elif result is None:
            err = gitinfo.get("error")
        st.update({"status": status, "updated_at": now_iso(), "error": err,
                   "runner": self.me if dst == "running" else None})
        task_out = {k: v for k, v in t.items() if k not in ("work_branch", "_state")}
        task_out["_state"] = st

        summary = {
            "id": tid, "title": t["title"], "status": status, "mode": t["mode"], "repo": t["repo"],
            "base_branch": t["base_branch"], "attempt": attempts, "error_kind": error_kind, "error": err,
            "duration_sec": round(time.time() - started, 1),
            "claude": None if result is None else {"ok": result.ok, "exit_code": result.exit_code,
                                                    "session_id": result.session_id,
                                                    "cost_usd": result.cost_usd, **result.raw},
            "codex_calls": [{k: c.get(k) for k in ("ts", "tool", "sandbox", "exit_code", "error_kind",
                                                   "duration_sec")} for c in codex_calls],
            "codex_unfinished_calls": unfinished, "warnings": warnings,
            "git": gitinfo, "finished_at": now_iso(), "runner": self.me,
        }
        report = self.render_report(t, summary, result, codex_calls)
        runlog = "\n".join(json.dumps(c, ensure_ascii=False) for c in codex_calls)

        def fn():
            self.queue.move(tid, "running", dst, task_out)
            self.queue.write_results(tid, {"report.md": redact(report),
                                           "result.json": redact(json.dumps(summary, ensure_ascii=False, indent=2)),
                                           "codex_calls.jsonl": redact(runlog)})
            self.queue.write_status_index()
            return True
        self.queue.transact(fn, f"agent-hub: {status} {tid}")
        self.history("finished", task=tid, status=status, error_kind=error_kind,
                     codex_calls=len(codex_calls))
        return status

    def render_report(self, t: dict, s: dict, result, codex_calls: list) -> str:
        g = s.get("git") or {}
        slug = t["repo"]
        lines = [f"# Task {t['id']}: {t['title']}", "",
                 f"- **Status:** {s['status']}  (attempt {s['attempt']}, {s['duration_sec']}s)",
                 f"- **Mode:** {t['mode']} — repo `{slug}`, base `{t['base_branch']}`",
                 f"- **Work branch:** `{t['work_branch']}`"
                 + (f" — pushed, compare: https://github.com/{slug}/compare/{t['base_branch']}...{t['work_branch']}"
                    if g.get("pushed") else " (not pushed)"),
                 f"- **Codex calls:** {len(codex_calls)}"
                 + (" — " + ", ".join(f"{c['tool']}:{'ok' if c['exit_code'] == 0 else c.get('error_kind')}"
                                      for c in codex_calls) if codex_calls else ""),
                 f"- **Finished:** {s['finished_at']} by `{s['runner']}`"]
        if s.get("warnings"):
            lines += ["", "## Warnings"] + [f"- {w}" for w in s["warnings"]]
        if s.get("error"):
            lines += ["", "## Error", "```", s["error"][-1500:], "```"]
        lines += ["", "## Claude Code report", "", (result.text if result and result.text else "_(no output)_")]
        if g.get("diffstat"):
            lines += ["", "## Diffstat", "```", g["diffstat"], "```"]
        lines += ["", "_This branch is not merged anywhere. Review it and open a PR manually if acceptable._"]
        return "\n".join(lines) + "\n"

    # ---------- loop ----------
    def run_once(self) -> str:
        self.queue.sync()
        if self.queue.paused():
            self.history("paused")
            return "paused"
        cd = self.cooldown_until()
        if cd and cd > datetime.now(timezone.utc):
            return f"cooldown until {cd:%Y-%m-%dT%H:%M:%SZ}"
        picked = self.pick()
        if not picked:
            return "idle"
        return self.process(*picked)

    def loop(self) -> None:
        while True:
            try:
                status = self.run_once()
            except (GitError, subprocess.TimeoutExpired, OSError) as e:
                self.history("loop_error", error=str(e)[:500])
                status = "error"
            log.info("cycle: %s", status)
            if status in ("idle", "paused", "error") or status.startswith("cooldown"):
                time.sleep(self.cfg["poll_interval_sec"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hub.runner")
    ap.add_argument("--config", default=os.environ.get("HUB_CONFIG", "config/hub.config.json"))
    ap.add_argument("command", choices=["once", "loop", "status"])
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    Path(cfg["state_dir"], "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(Path(cfg["state_dir"], "logs", "runner.log"),
                                                      encoding="utf-8")])
    r = Runner(cfg)
    if a.command == "status":
        r.queue.sync()
        print((r.queue.root / "status.md").read_text(encoding="utf-8")
              if (r.queue.root / "status.md").exists() else "no status yet")
        return 0
    if a.command == "once":
        print(r.run_once())
        return 0
    r.loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
