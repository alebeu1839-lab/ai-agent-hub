"""Isolated, opt-in worker foundation for the My Addness repository.

This module intentionally owns a separate config, lock, lease, state and queue tree.
Execution is injectable and remains a stub until a later stage supplies an executor.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .addness import make_client
from .redact import redact

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,63}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
CHECKPOINT_RE = re.compile(r"\[my-addness-worker:checkpoint run=([^ ]+) sha=([0-9a-fA-F]{40}) phase=([\w-]+)\]")

DEFAULTS = {
    "worker_id": "my-addness-isolated", "enabled": False, "execute_enabled": False,
    "target_repo": "alebeu1839-lab/-my-addness",
    "target_clone_url": "https://github.com/alebeu1839-lab/-my-addness.git",
    "target_branch": "codex/today-bulk-selection", "target_pr": 2,
    "denied_branches": ["main", "master", "production", "release/*", "gh-pages"],
    "denied_prs": [3], "source_goal_id": "afe1fa15-e2d2-41fc-a6c0-86b8a9eefcf2",
    "bridge_goal_id": "655c2d75-6c62-4c43-98d5-bd61c5aad9f9",
    "state_dir": "state-isolated/my-addness", "lease_ttl_sec": 3600,
    "addness": {"client": "claude_mcp", "fake_store": "", "mcp_server_name": "addness",
                "claude_timeout_sec": 300, "model": None},
}


class WorkerConfigError(ValueError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = json.loads(json.dumps(base))
    for key, value in over.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_worker_config(path: str | Path, hub_state_dir: str | Path | None = None) -> dict:
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkerConfigError("worker config unreadable") from exc
    if not isinstance(data, dict):
        raise WorkerConfigError("worker config must be an object")
    cfg = _merge(DEFAULTS, data)
    branch = cfg.get("target_branch")
    repo = cfg.get("target_repo")
    if not isinstance(repo, str) or not repo.strip() or any(c in repo for c in "*?["):
        raise WorkerConfigError("target_repo invalid")
    if not isinstance(branch, str) or not branch.strip() or any(c in branch for c in "*?["):
        raise WorkerConfigError("target_branch invalid")
    if any(fnmatch.fnmatchcase(branch, p) for p in cfg.get("denied_branches", [])):
        raise WorkerConfigError("target_branch denied")
    if cfg.get("target_pr") in cfg.get("denied_prs", []):
        raise WorkerConfigError("target_pr denied")
    clone_url = cfg.get("target_clone_url")
    try:
        parsed_clone_url = urlsplit(clone_url) if isinstance(clone_url, str) else None
    except ValueError:
        parsed_clone_url = None
    if (not isinstance(clone_url, str) or not clone_url.startswith("https://") or
            parsed_clone_url is None or parsed_clone_url.scheme != "https" or
            not parsed_clone_url.netloc or "@" in parsed_clone_url.netloc or
            parsed_clone_url.query or parsed_clone_url.fragment or
            "?" in clone_url or "#" in clone_url):
        raise WorkerConfigError("target_clone_url invalid")
    if not isinstance(cfg.get("source_goal_id"), str) or not cfg["source_goal_id"] or not isinstance(cfg.get("bridge_goal_id"), str) or not cfg["bridge_goal_id"]:
        raise WorkerConfigError("goal ids invalid")
    if not isinstance(cfg.get("state_dir"), str) or not cfg["state_dir"].strip():
        raise WorkerConfigError("state_dir invalid")
    if not isinstance(cfg.get("enabled"), bool) or not isinstance(cfg.get("execute_enabled"), bool):
        raise WorkerConfigError("worker enable flags must be booleans")
    if not isinstance(cfg.get("target_pr"), int) or isinstance(cfg.get("target_pr"), bool):
        raise WorkerConfigError("target_pr invalid")
    try:
        ttl = int(cfg["lease_ttl_sec"])
    except (TypeError, ValueError) as exc:
        raise WorkerConfigError("lease_ttl_sec invalid") from exc
    if ttl <= 0:
        raise WorkerConfigError("lease_ttl_sec invalid")
    cfg["lease_ttl_sec"] = ttl
    root = path.parent.parent if path.parent.name == "config" else path.parent
    state = Path(cfg["state_dir"])
    if not state.is_absolute():
        state = (root / state).resolve()
    else:
        state = state.resolve()
    hub_states = {(root / "state").resolve()}
    if hub_state_dir:
        hub_states.add(Path(hub_state_dir).resolve())
    if any(
        state == hub_state or state in hub_state.parents or hub_state in state.parents
        for hub_state in hub_states
    ):
        raise WorkerConfigError("state_dir overlaps default hub state")
    cfg["state_dir"] = str(state)
    cfg["_repo_root"] = str(root)
    return cfg


@dataclass
class Request:
    run_id: str
    repo: str
    branch: str
    pr: int | None
    goal_id: str
    expected_head: str | None = None
    mode: str = "inspect"

    @classmethod
    def from_value(cls, value):
        return value if isinstance(value, cls) else cls(**value)


@dataclass
class Decision:
    ok: bool
    reason: str


class LeaseBusy(Exception):
    pass


class LeaseExpired(Exception):
    pass


class LeaseMismatch(Exception):
    pass


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Lease:
    def __init__(self, path: str | Path, ttl: int, history: Callable | None = None):
        self.path, self.ttl, self.history = Path(path), int(ttl), history

    def read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or not isinstance(data.get("run_id"), str) or
                    not isinstance(data.get("holder"), str) or
                    not isinstance(data.get("expires_at"), (int, float))):
                raise ValueError("lease unreadable")
            return data
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise ValueError("lease unreadable") from exc

    def acquire(self, run_id: str, holder: str) -> dict:
        now = time.time()
        obj = {"run_id": run_id, "holder": holder, "acquired_at": now,
               "acquired_at_iso": _utc(), "expires_at": now + self.ttl,
               "expires_at_iso": datetime.fromtimestamp(now + self.ttl, timezone.utc).isoformat().replace("+00:00", "Z")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            old = self.read()
            if old and float(old.get("expires_at", 0)) <= now:
                raise LeaseExpired("expired lease: manual release required")
            raise LeaseBusy("active lease")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        return obj

    def release(self, run_id: str, holder: str) -> None:
        old = self.read()
        if not old or old.get("run_id") != run_id or old.get("holder") != holder:
            raise LeaseMismatch("lease mismatch")
        self.path.unlink()

    def manual_release(self, run_id: str) -> None:
        old = self.read()
        if not old or old.get("run_id") != run_id:
            raise LeaseMismatch("lease run_id mismatch")
        self.path.unlink()
        if self.history:
            self.history("lease_manual_release", run_id=run_id)


class WorkerLock:
    def __init__(self, path: Path, ttl: int):
        self.path, self.ttl, self.fd = path, ttl, None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                age = 0
            if age > self.ttl:
                return "stale worker lock: manual removal required"
            return "locked"
        os.write(self.fd, str(os.getpid()).encode())
        return "ok"

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class IsolatedWorker:
    def __init__(self, cfg: dict, client=None, head_resolver=None):
        self.cfg = cfg
        self.state_dir = Path(cfg["state_dir"])
        self.client = client or make_client({"addness": cfg["addness"], "claude": {"bin": "claude"}}, self.state_dir)
        self.head_resolver = head_resolver or default_head_resolver
        self.lease = Lease(self.state_dir / "lease.json", cfg["lease_ttl_sec"], self.history)

    def history(self, event, **fields):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "history.jsonl").open("a", encoding="utf-8") as f:
            entry = json.loads(redact(json.dumps({"event": event, "at": _utc(), **fields}, ensure_ascii=False)))
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _state(self):
        path = self.state_dir / "state.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("runs"), dict):
                raise ValueError("state unreadable")
            return state
        except FileNotFoundError:
            return {"runs": {}}
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("state unreadable") from exc

    def _save_state(self, state):
        _atomic_json(self.state_dir / "state.json", state)

    def _goal_text(self, goal):
        return "\n".join([str(goal.get("body") or ""), *(str(c.get("body", "")) for c in goal.get("comments") or [])])

    def _checkpoint(self, goal, run_id):
        matches = [m for m in CHECKPOINT_RE.finditer(self._goal_text(goal)) if m.group(1) == run_id]
        if not matches:
            return None
        match = matches[-1]
        return {"run_id": match.group(1), "sha": match.group(2).lower(), "phase": match.group(3)}

    def admit(self, req, head_resolver=None) -> Decision:
        req = Request.from_value(req)
        if not self.cfg.get("enabled") and req.mode != "inspect":
            return Decision(False, "worker disabled")
        if not RUN_ID_RE.fullmatch(str(req.run_id)):
            return Decision(False, "invalid run_id")
        if req.mode not in ("inspect", "dry-run", "execute"):
            return Decision(False, "unknown mode")
        if req.mode == "execute" and not self.cfg.get("execute_enabled"):
            return Decision(False, "execute not enabled")
        if req.repo != self.cfg["target_repo"]:
            return Decision(False, "repo not allowed")
        if req.branch in self.cfg.get("denied_branches", []) or req.branch != self.cfg["target_branch"]:
            return Decision(False, "branch not allowed")
        if req.pr in self.cfg.get("denied_prs", []):
            return Decision(False, "pr denied")
        if req.pr is not None and not isinstance(req.pr, int):
            return Decision(False, "pr not allowed")
        if req.pr is not None and req.pr != self.cfg["target_pr"]:
            return Decision(False, "pr not allowed")
        if req.mode in ("dry-run", "execute") and req.pr is None:
            return Decision(False, "pr required")
        if req.goal_id != self.cfg["source_goal_id"]:
            return Decision(False, "goal not allowed")
        try:
            state_run = self._state().get("runs", {}).get(req.run_id)
        except ValueError:
            return Decision(False, "state unreadable")
        if state_run and state_run.get("status") in ("done", "failed"):
            return Decision(False, "duplicate run_id")
        try:
            lease = self.lease.read()
        except ValueError:
            return Decision(False, "lease unreadable")
        if lease is not None:
            if float(lease.get("expires_at", 0)) <= time.time():
                return Decision(False, "expired lease: manual release required")
            if lease.get("run_id") != req.run_id:
                return Decision(False, "active lease")
        resolver = head_resolver or self.head_resolver
        try:
            head = resolver(self.cfg["target_clone_url"], req.branch)
        except Exception:
            return Decision(False, "head unknown")
        if not isinstance(head, str) or not SHA_RE.fullmatch(head):
            return Decision(False, "head unknown")
        if req.expected_head and req.expected_head.lower() != str(head).lower():
            return Decision(False, "head mismatch")
        if state_run and state_run.get("status") == "interrupted":
            try:
                goal = self.client.get_task(self.cfg["source_goal_id"])
            except Exception:
                return Decision(False, "resume head mismatch")
            checkpoint = self._checkpoint(goal, req.run_id)
            if not checkpoint or checkpoint["sha"] != str(head).lower():
                return Decision(False, "resume head mismatch")
        if state_run and state_run.get("status") == "running" and lease is None:
            try:
                goal = self.client.get_task(self.cfg["source_goal_id"])
            except Exception:
                return Decision(False, "stale running run: checkpoint required")
            checkpoint = self._checkpoint(goal, req.run_id)
            if not checkpoint or checkpoint["sha"] != str(head).lower():
                return Decision(False, "stale running run: checkpoint required")
        return Decision(True, "ok")

    def inspect(self, req):
        req = Request.from_value(req)
        decision = self.admit(req)
        remote = None
        try:
            remote = self.head_resolver(self.cfg["target_clone_url"], req.branch)
        except Exception:
            pass
        try:
            goal = self.client.get_task(self.cfg["source_goal_id"])
        except Exception:
            goal = {}
        checkpoint = self._checkpoint(goal, req.run_id)
        return {"decision": asdict(decision), "remote_head": remote, "last_checkpoint": checkpoint,
                "checkpoint_matches_head": bool(checkpoint and remote and checkpoint["sha"] == str(remote).lower())}

    def dry_run(self, req):
        req = Request.from_value(req)
        info = self.inspect(req)
        if not info["decision"]["ok"]:
            return info
        lock = WorkerLock(self.state_dir / "worker.lock", self.cfg["lease_ttl_sec"])
        status = lock.acquire()
        if status != "ok":
            info["decision"] = asdict(Decision(False, status))
            return info
        try:
            try:
                self.lease.acquire(req.run_id, self.cfg["worker_id"])
            except LeaseExpired:
                info["decision"] = asdict(Decision(False, "expired lease: manual release required"))
            except LeaseBusy:
                info["decision"] = asdict(Decision(False, "active lease"))
            else:
                self.lease.release(req.run_id, self.cfg["worker_id"])
        finally:
            lock.release()
        info["plan"] = {"repo": req.repo, "branch": req.branch, "pr": req.pr, "mode": req.mode, "head": info["remote_head"]}
        return info

    def process(self, req, executor=None):
        req = Request.from_value(req)
        decision = self.admit(req)
        if not decision.ok:
            return {"status": "rejected", "reason": decision.reason}
        if req.mode != "execute":
            return {"status": "rejected", "reason": "execute mode required"}
        lock = WorkerLock(self.state_dir / "worker.lock", self.cfg["lease_ttl_sec"])
        lock_status = lock.acquire()
        if lock_status != "ok":
            return {"status": lock_status}
        lease_acquired = False
        state = {"runs": {}}
        try:
            decision = self.admit(req)
            if not decision.ok:
                return {"status": "rejected", "reason": decision.reason}
            try:
                remote = self.head_resolver(self.cfg["target_clone_url"], req.branch)
            except Exception:
                remote = None
            if not isinstance(remote, str) or not SHA_RE.fullmatch(remote):
                return {"status": "rejected", "reason": "head unknown"}
            self.lease.acquire(req.run_id, self.cfg["worker_id"])
            lease_acquired = True
            state = self._state()
            state.setdefault("runs", {})
            prior = state["runs"].get(req.run_id, {})
            if prior.get("status") in ("done", "failed"):
                return {"status": "rejected", "reason": "duplicate run_id"}
            for name in ("inbox", "running", "done", "failed"):
                (self.state_dir / "queue" / name).mkdir(parents=True, exist_ok=True)
            state["runs"][req.run_id] = {"status": "running", "phase": "execute", "checkpoint_sha": prior.get("checkpoint_sha"), "started_at": prior.get("started_at", _utc()), "updated_at": _utc(), "reason": None}
            self._save_state(state)
            goal = self.client.get_task(self.cfg["source_goal_id"])
            checkpoint = self._checkpoint(goal, req.run_id)
            if checkpoint and checkpoint["sha"] != str(remote).lower():
                raise RuntimeError("checkpoint/head mismatch")
            if prior.get("status") == "interrupted" and (not checkpoint or checkpoint["sha"] != str(remote).lower()):
                raise RuntimeError("resume head mismatch")
            if executor is None:
                def executor(ctx):
                    raise NotImplementedError("execution is a later stage")
            result = executor({"request": req, "head": remote, "goal": goal, "worker": self})
            reported = result.get("head") if isinstance(result, dict) else None
            if not isinstance(reported, str) or not SHA_RE.fullmatch(reported):
                raise RuntimeError("head race")
            try:
                after = self.head_resolver(self.cfg["target_clone_url"], req.branch)
            except Exception:
                after = None
            if not isinstance(after, str) or not SHA_RE.fullmatch(after) or after.lower() != reported.lower():
                raise RuntimeError("head race")
            sha = reported.lower()
            state["runs"][req.run_id].update(status="done", phase="done", checkpoint_sha=sha, updated_at=_utc(), reason=None)
            self._save_state(state)
            self._write_source(f"[my-addness-worker:done run={req.run_id} status=done sha={sha}]", f"### Isolated worker completed\nRun `{req.run_id}` completed at `{sha}`.")
            self.client.add_comment(
                self.cfg["source_goal_id"],
                redact(f"[my-addness-worker:checkpoint run={req.run_id} sha={sha} phase=done]"),
            )
            self.client.add_comment(self.cfg["bridge_goal_id"], redact(f"[my-addness-worker:progress run={req.run_id} status=done sha={sha}] Isolated worker completed."))
            return {"status": "done", "head": sha}
        except LeaseBusy:
            return {"status": "rejected", "reason": "active lease"}
        except LeaseExpired:
            return {"status": "rejected", "reason": "expired lease: manual release required"}
        except KeyboardInterrupt:
            self._finish(state, req.run_id, "interrupted", "interrupted", "KeyboardInterrupt")
            self._writeback_best_effort(req.run_id, "interrupted", None)
            raise
        except Exception as exc:
            reason = str(exc) or type(exc).__name__
            status = "interrupted" if reason == "resume head mismatch" else "failed"
            self._finish(state, req.run_id, status, status, reason)
            self._writeback_best_effort(req.run_id, status, reason)
            return {"status": status, "reason": redact(reason)}
        finally:
            if lease_acquired:
                try:
                    self.lease.release(req.run_id, self.cfg["worker_id"])
                except Exception as exc:
                    self.history("lease_release_failed", run_id=req.run_id, error=str(exc))
            lock.release()

    def _finish(self, state, run_id, status, phase, reason):
        state.setdefault("runs", {})
        state["runs"].setdefault(run_id, {})
        state["runs"][run_id].update(status=status, phase=phase, updated_at=_utc(), reason=redact(str(reason))[:300])
        self._save_state(state)

    def _write_source(self, comment, detail):
        self.client.append_detail(self.cfg["source_goal_id"], redact(detail))
        self.client.add_comment(self.cfg["source_goal_id"], redact(comment))

    def _writeback_best_effort(self, run_id, status, reason):
        marker = f"[my-addness-worker:{status} run={run_id}" + (f" reason={redact(reason)[:100]}" if reason else "") + "]"
        try:
            self.client.add_comment(self.cfg["source_goal_id"], redact(marker))
        except Exception as exc:
            self.history("writeback_failed", run_id=run_id, error=str(exc))

    def status(self):
        return self._state()


def default_head_resolver(clone_url: str, branch: str) -> str | None:
    proc = subprocess.run(["git", "ls-remote", clone_url, f"refs/heads/{branch}"], capture_output=True,
                          text=True, timeout=60, shell=False)
    if proc.returncode != 0:
        return None
    line = next((line for line in proc.stdout.splitlines() if line.endswith(f"refs/heads/{branch}")), "")
    sha = line.split()[0] if line else None
    return sha if sha and SHA_RE.fullmatch(sha) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hub.isolated_worker")
    ap.add_argument("--config", default="config/my-addness-worker.json")
    ap.add_argument("command", choices=["inspect", "dry-run", "status", "release-lease"])
    ap.add_argument("--run-id")
    ap.add_argument("--repo")
    ap.add_argument("--branch")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--goal")
    ap.add_argument("--expected-head")
    args = ap.parse_args(argv)
    try:
        cfg = load_worker_config(args.config)
    except WorkerConfigError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    worker = IsolatedWorker(cfg)
    if args.command == "status":
        result = worker.status()
    elif args.command == "release-lease":
        if not args.run_id:
            result = {"status": "refused", "reason": "run_id required"}
        else:
            try:
                worker.lease.manual_release(args.run_id)
                result = {"status": "released"}
            except LeaseMismatch as exc:
                result = {"status": "refused", "reason": str(exc)}
    else:
        req = Request(args.run_id or "", args.repo or "", args.branch or "", args.pr, args.goal or "", args.expected_head, args.command)
        result = worker.inspect(req) if args.command == "inspect" else worker.dry_run(req)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
