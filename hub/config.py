"""Config loading and task validation (the security gate for external instructions)."""
from __future__ import annotations

import copy
import fnmatch
import json
import re
from pathlib import Path

DEFAULTS = {
    "runner_id": "runner",
    "queue_repo_url": "",
    "queue_branch": "agent-queue",
    "queue_dir": "queue",
    "allowed_repos": {},
    "work_branch_prefix": "agent/",
    "protected_branches": ["main", "master", "production", "release/*", "gh-pages"],
    "push_work_branch": True,
    "allowed_modes": ["plan"],
    "security": {
        "verify_submitter": True,
        "require_signed_commit": False,
        "allowed_submitters": [],
        "max_instruction_chars": 8000,
    },
    "claude": {"bin": "claude", "timeout_sec": 2400, "max_budget_usd": 5, "restricted": True,
               "model": None},
    "codex": {"bin": "codex", "timeout_sec": 1200, "model": None},
    "retry": {
        "max_attempts": 3,
        "base_backoff_sec": 120,
        "max_backoff_sec": 3600,
        "usage_limit_cooldown_sec": 1800,
    },
    "billing": {
        "subscription_only": True,
        "claude_allowed_auth_methods": ["oauth_token", "oauth", "claude.ai", "claudeai", "subscription"],
        "require_codex_subscription": True,
    },
    "poll_interval_sec": 60,
    "state_dir": "state",
    # Addness intake (hub/addness_intake.py). Off unless enabled in the local config.
    "addness": {
        "enabled": False,
        "complete_on_pass": False,
        "client": "claude_mcp",          # claude_mcp (real, via Claude Code's Addness MCP) | fake
        "fake_store": "",
        "mcp_server_name": "addness",
        "model": None,
        "claude_timeout_sec": 300,
        "title_prefix": "【Claude Code PC】",
        "allowed_parent_titles": [],     # empty = any parent; otherwise one ancestor must match
        "excluded_goal_ids": [],
        "excluded_path_keywords": ["My Addness"],
        "require_go_marker": None,       # e.g. "実行指示": comment/body must contain it
        "allowed_owner_names": [],       # if set, the Addness task owner must be one of these
        "target_repo": "",
        "base_branch": "main",
        "mode": "implement",
        "acceptance": [],
        "max_tasks_per_cycle": 1,
        "lock_ttl_sec": 7200,
    },
}

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,63}$")
MODES = {"plan", "implement"}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "allowed_repos":
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> dict:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    cfg = _merge(DEFAULTS, data)
    sd = Path(cfg["state_dir"])
    if not sd.is_absolute():
        sd = (path.parent.parent / sd).resolve() if path.parent.name == "config" else (path.parent / sd).resolve()
    cfg["state_dir"] = str(sd)
    return cfg


def branch_matches(branch: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(branch, p) for p in patterns)


class TaskRejected(Exception):
    """Task failed validation. Never retried."""


def validate_task(task: dict, cfg: dict) -> dict:
    """Return a normalised task or raise TaskRejected. Only data, never code, is accepted."""
    if not isinstance(task, dict):
        raise TaskRejected("task must be a JSON object")
    allowed_keys = {"id", "title", "instructions", "repo", "base_branch", "mode",
                    "requested_by", "acceptance", "created_at", "priority"}
    unknown = set(task) - allowed_keys - {"_state"}
    if unknown:
        raise TaskRejected(f"unknown fields: {sorted(unknown)}")

    tid = task.get("id")
    if not isinstance(tid, str) or not TASK_ID_RE.match(tid):
        raise TaskRejected("id must match ^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")

    instr = task.get("instructions")
    max_chars = cfg["security"]["max_instruction_chars"]
    if not isinstance(instr, str) or not instr.strip():
        raise TaskRejected("instructions is required")
    if len(instr) > max_chars:
        raise TaskRejected(f"instructions longer than {max_chars} chars")

    repo = task.get("repo")
    repos = cfg["allowed_repos"]
    if repo not in repos:
        raise TaskRejected(f"repo not in allowlist: {repo!r}")

    base = task.get("base_branch") or "main"
    if not isinstance(base, str) or ".." in base or base.startswith("-"):
        raise TaskRejected("invalid base_branch")
    if not branch_matches(base, repos[repo].get("allowed_base_branches", [])):
        raise TaskRejected(f"base_branch {base!r} not allowed for {repo}")

    mode = task.get("mode") or "plan"
    if mode not in MODES:
        raise TaskRejected(f"mode must be one of {sorted(MODES)}")
    if mode not in cfg["allowed_modes"]:
        raise TaskRejected(f"mode {mode!r} is disabled on this runner")

    acceptance = task.get("acceptance") or []
    if not isinstance(acceptance, list) or not all(isinstance(a, str) for a in acceptance):
        raise TaskRejected("acceptance must be a list of strings")

    work_branch = cfg["work_branch_prefix"] + tid
    if branch_matches(work_branch, cfg["protected_branches"]):
        raise TaskRejected("work branch would be protected")

    return {
        "id": tid,
        "title": str(task.get("title") or tid)[:200],
        "instructions": instr,
        "repo": repo,
        "base_branch": base,
        "mode": mode,
        "requested_by": str(task.get("requested_by") or "unknown")[:100],
        "acceptance": acceptance[:20],
        "work_branch": work_branch,
        "_state": task.get("_state") or {},
    }
