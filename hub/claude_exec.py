"""Launch Claude Code headless (`claude -p`) for one task with a restricted tool set."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .billing import subscription_env
from .redact import redact

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tools Claude may use without prompting. Anything else is denied in -p mode.
BASE_ALLOWED = [
    "Read", "Glob", "Grep",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "mcp__codex__codex_review",
]
IMPLEMENT_ALLOWED = [
    "Edit", "Write",
    "Bash(git add:*)",
    "Bash(npm test:*)", "Bash(npm run test:*)", "Bash(npm run lint:*)",
    "Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)",
    "Bash(python -m unittest:*)", "Bash(python3 -m unittest:*)",
    "mcp__codex__codex_implement", "mcp__codex__codex_test",
]
ALWAYS_DENIED = [
    "Bash(git push:*)", "Bash(git remote:*)", "Bash(git checkout main:*)", "Bash(git switch main:*)",
    "Bash(git reset --hard:*)", "Bash(curl:*)", "Bash(wget:*)", "Bash(rm -rf:*)",
    "Bash(gh:*)", "Bash(npx wrangler:*)", "Bash(wrangler:*)", "WebFetch", "WebSearch",
]

TRANSIENT_MARKERS = ("rate limit", "rate_limit", "429", "overloaded", "529", "timed out", "timeout",
                     "econnreset", "etimedout", "enotfound", "network", "connection", "503", "502")
USAGE_MARKERS = ("usage limit", "usage_limit", "limit reached", "quota", "credit balance")


@dataclass
class ClaudeResult:
    ok: bool
    exit_code: int
    text: str = ""
    session_id: str | None = None
    cost_usd: float | None = None
    error_kind: str | None = None  # transient | usage_limit | fatal | timeout
    raw: dict = field(default_factory=dict)
    stderr_tail: str = ""


def build_prompt(task: dict, resume: bool) -> str:
    if resume:
        return ("The previous run of this task was interrupted. Inspect the current state of the "
                "working directory (git status / git diff), continue from where you left off, and "
                "finish with the required final answer format.")
    acc = "\n".join(f"- {a}" for a in task.get("acceptance", [])) or "- (none given)"
    return (f"# Task {task['id']}: {task['title']}\n\nMode: {task['mode']}\n"
            f"Requested by: {task['requested_by']}\n\n## Instructions\n{task['instructions']}\n\n"
            f"## Acceptance criteria\n{acc}\n")


def write_mcp_config(path: Path, workspace: Path, task: dict, cfg: dict, bridge_log: Path) -> None:
    env = {
        "CODEX_BRIDGE_WORKSPACE": str(workspace),
        "CODEX_BRIDGE_MAX_SANDBOX": "workspace-write" if task["mode"] == "implement" else "read-only",
        "CODEX_BRIDGE_LOG": str(bridge_log),
        "CODEX_BRIDGE_TIMEOUT": str(cfg["codex"]["timeout_sec"]),
        "CODEX_BIN": shutil.which(os.environ.get("CODEX_BIN", cfg["codex"]["bin"]))
                     or os.environ.get("CODEX_BIN", cfg["codex"]["bin"]),
    }
    if cfg["codex"].get("model"):
        env["CODEX_BRIDGE_MODEL"] = cfg["codex"]["model"]
    conf = {"mcpServers": {"codex": {
        "type": "stdio",
        "command": sys.executable,
        "args": [str(REPO_ROOT / "hub" / "codex_mcp_bridge.py")],
        "env": env,
    }}}
    path.write_text(json.dumps(conf, indent=2), encoding="utf-8")


def classify_failure(text: str) -> str:
    t = text.lower()
    if any(m in t for m in USAGE_MARKERS):
        return "usage_limit"
    if any(m in t for m in TRANSIENT_MARKERS):
        return "transient"
    return "fatal"


def run_claude(task: dict, workspace: Path, cfg: dict, run_dir: Path,
               resume_session: str | None = None) -> ClaudeResult:
    run_dir.mkdir(parents=True, exist_ok=True)
    mcp_path = run_dir / "mcp.json"
    write_mcp_config(mcp_path, workspace, task, cfg, run_dir / "codex_calls.jsonl")
    system = (REPO_ROOT / "prompts" / "claude-orchestrator.md").read_text(encoding="utf-8")
    system = system.replace("{work_branch}", task["work_branch"]).replace("{base_branch}", task["base_branch"])
    sys_path = run_dir / "system-prompt.md"
    sys_path.write_text(system, encoding="utf-8")

    implement = task["mode"] == "implement"
    allowed = BASE_ALLOWED + (IMPLEMENT_ALLOWED if implement else [])
    # Permission rules go in a settings file (not argv): avoids Windows cmd.exe quoting/length limits.
    settings_path = run_dir / "settings.json"
    settings_path.write_text(json.dumps({"permissions": {
        "defaultMode": "default", "allow": allowed, "deny": ALWAYS_DENIED}}, indent=2), encoding="utf-8")

    ccfg = cfg["claude"]
    claude_bin = os.environ.get("CLAUDE_BIN", ccfg["bin"])
    claude_bin = shutil.which(claude_bin) or claude_bin  # Windows: resolve claude.cmd via PATHEXT
    cmd = [claude_bin, "-p", "--output-format", "json",
           "--mcp-config", str(mcp_path), "--strict-mcp-config",
           "--settings", str(settings_path),
           "--append-system-prompt-file", str(sys_path),
           "--permission-mode", "default"]
    if ccfg.get("restricted", True):
        # --restricted: ignore user/project/local settings, confine file tools to the workspace,
        # refuse bypassPermissions. Bash is re-enabled only so the allowlist above can apply.
        tools = "Read,Glob,Grep,Bash" + (",Edit,Write" if implement else "")
        cmd += ["--restricted", "--tools", tools]
    else:
        cmd += ["--setting-sources", ""]
    if ccfg.get("max_budget_usd"):
        cmd += ["--max-budget-usd", str(ccfg["max_budget_usd"])]
    if ccfg.get("model"):
        cmd += ["--model", ccfg["model"]]
    if resume_session:
        cmd += ["--resume", resume_session]
    prompt = build_prompt(task, bool(resume_session))

    # Claude Code's default MCP tool timeout is short (~60s); Codex runs take minutes.
    env = subscription_env()  # strip API keys: subscription billing only
    env["MCP_TOOL_TIMEOUT"] = str((int(cfg["codex"]["timeout_sec"]) + 120) * 1000)
    env.setdefault("MCP_TIMEOUT", "60000")
    try:
        proc = subprocess.run(cmd, cwd=workspace, input=prompt, capture_output=True, env=env,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=ccfg["timeout_sec"])
    except FileNotFoundError:
        return ClaudeResult(False, 127, error_kind="fatal", stderr_tail="claude CLI not found")
    except subprocess.TimeoutExpired:
        return ClaudeResult(False, 124, error_kind="timeout", stderr_tail="claude timed out")

    (run_dir / "claude_stdout.json").write_text(redact(proc.stdout), encoding="utf-8")
    stderr_tail = redact(proc.stderr)[-3000:]
    data: dict = {}
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        data = {}
    text = redact(str(data.get("result", "")))
    is_error = proc.returncode != 0 or bool(data.get("is_error")) or not data
    res = ClaudeResult(ok=not is_error, exit_code=proc.returncode, text=text,
                       session_id=data.get("session_id"), cost_usd=data.get("total_cost_usd"),
                       raw={k: data.get(k) for k in ("subtype", "num_turns", "duration_ms",
                                                      "permission_denials", "terminal_reason")},
                       stderr_tail=stderr_tail)
    if is_error:
        res.error_kind = classify_failure(f"{text}\n{stderr_tail}\n{data.get('subtype', '')}")
    return res
