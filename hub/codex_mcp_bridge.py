#!/usr/bin/env python3
"""Minimal MCP (stdio) server that lets Claude Code delegate work to the Codex CLI.

Why a bridge instead of ``codex mcp-server``: recent Codex CLI releases (e.g. 0.170)
no longer ship an ``mcp-server`` subcommand, and wrapping ``codex exec`` lets us pin
safety limits that the model cannot change:

* the working directory is fixed to CODEX_BRIDGE_WORKSPACE (the task worktree)
* sandbox is capped by CODEX_BRIDGE_MAX_SANDBOX (read-only | workspace-write);
  ``danger-full-access`` / bypass flags are never used
* every call has a timeout and is appended to CODEX_BRIDGE_LOG (JSONL) for the runner

Tools exposed: codex_implement, codex_test, codex_review.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.billing import subscription_env  # noqa: E402
from hub.redact import redact  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SANDBOX_ORDER = ["read-only", "workspace-write"]

TOOLS = [
    {
        "name": "codex_implement",
        "description": "Ask Codex to implement a well-scoped code change inside the task workspace. "
                       "Give precise instructions: files, behaviour, constraints, how to verify.",
        "inputSchema": {"type": "object", "properties": {
            "instructions": {"type": "string", "description": "What Codex should implement."}},
            "required": ["instructions"]},
    },
    {
        "name": "codex_test",
        "description": "Ask Codex to write and/or run tests for the current workspace changes and report results.",
        "inputSchema": {"type": "object", "properties": {
            "instructions": {"type": "string", "description": "What to test and how."}},
            "required": ["instructions"]},
    },
    {
        "name": "codex_review",
        "description": "Ask Codex for a read-only code review. Reviews the uncommitted changes by default, "
                       "or the given files when `paths` is set (use this in plan mode, where there is no diff).",
        "inputSchema": {"type": "object", "properties": {
            "focus": {"type": "string", "description": "Optional review focus."},
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "Optional workspace-relative files to review instead of the diff."}}},
    },
]

ROLE_PREFIX = {
    "codex_implement": "You are the implementer. Make the requested change in this repository. "
                       "Do not push, do not touch git remotes, do not read or print secrets. "
                       "Finish with a short summary of files changed and how you verified.\n\nTask:\n",
    "codex_test": "You are the tester. Write or run tests for the current changes. Do not push. "
                  "Report each command run and its pass/fail result.\n\nTask:\n",
    "codex_review": "You are the reviewer. Review the uncommitted changes (git diff) in this repository. "
                    "Do not modify files. List concrete bugs/risks with file:line and severity, then a verdict "
                    "(APPROVE / REQUEST_CHANGES).\n\nFocus:\n",
}
TOOL_SANDBOX = {"codex_implement": "workspace-write", "codex_test": "workspace-write",
                "codex_review": "read-only"}


def classify(text: str) -> str | None:
    t = text.lower()
    if any(k in t for k in ("not logged in", "401", "unauthorized", "codex login")):
        return "auth"
    if any(k in t for k in ("usage limit", "rate limit", "429", "quota")):
        return "usage_limit"
    if any(k in t for k in ("timed out", "connection reset", "connection refused", "network",
                            "proxy connection failed", "failed to connect")):
        return "network"
    return None


_PREFLIGHT: tuple[bool, str] | None = None


def codex_environment() -> dict[str, str]:
    """Build the child environment without the Codex app's registered-core marker.

    When inherited from the Codex desktop app, this marker makes standalone
    ``codex exec`` try the app-registered runtime and fail to provision it.
    """
    env = subscription_env()
    env.pop("CODEX_WINDOWS_REGISTERED_CORE", None)
    return env


def preflight(codex: str) -> tuple[bool, str]:
    """Fail fast if Codex is missing or not logged in (otherwise `codex exec` can hang retrying)."""
    global _PREFLIGHT
    if _PREFLIGHT is None:
        try:
            p = subprocess.run([*([sys.executable] if codex.endswith(".py") else []), codex, "login", "status"], stdin=subprocess.DEVNULL, capture_output=True,
                               env=codex_environment(),
                               text=True, encoding="utf-8", errors="replace", timeout=30)
            out = (p.stdout + p.stderr).strip()
            subscription = "chatgpt" in out.lower() and "api key" not in out.lower()
            if p.returncode == 0 and not subscription:
                _PREFLIGHT = (False, "billing: Codex is not using a ChatGPT login (API key = metered). " + out[-200:])
            else:
                _PREFLIGHT = (p.returncode == 0, out[-300:] or f"exit {p.returncode}")
        except FileNotFoundError:
            _PREFLIGHT = (False, f"codex binary not found: {codex}")
        except subprocess.TimeoutExpired:
            _PREFLIGHT = (False, "codex login status timed out")
    return _PREFLIGHT


def log_call(entry: dict) -> None:
    path = os.environ.get("CODEX_BRIDGE_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_codex(tool: str, args: dict) -> tuple[str, bool]:
    ws = os.environ.get("CODEX_BRIDGE_WORKSPACE")
    if not ws or not Path(ws).is_dir():
        return "CODEX_ERROR_KIND: config\nCODEX_BRIDGE_WORKSPACE is not set to a directory", True
    max_sb = os.environ.get("CODEX_BRIDGE_MAX_SANDBOX", "read-only")
    if max_sb not in SANDBOX_ORDER:
        max_sb = "read-only"
    want = TOOL_SANDBOX[tool]
    if SANDBOX_ORDER.index(want) > SANDBOX_ORDER.index(max_sb):
        return (f"CODEX_ERROR_KIND: forbidden\n{tool} needs sandbox '{want}' but this task is limited "
                f"to '{max_sb}' (plan mode). Use codex_review or plan only."), True

    body = args.get("instructions") or args.get("focus") or "General review."
    if not isinstance(body, str) or len(body) > 20000:
        return "CODEX_ERROR_KIND: input\ninstructions must be a string under 20000 chars", True
    prompt = ROLE_PREFIX[tool] + body
    paths = args.get("paths") or []
    if tool == "codex_review" and paths:
        if not isinstance(paths, list) or len(paths) > 50 or not all(isinstance(x, str) for x in paths):
            return "CODEX_ERROR_KIND: input\npaths must be a list of at most 50 strings", True
        root = Path(ws).resolve()
        for x in paths:
            if not (root / x).resolve().is_relative_to(root):
                return f"CODEX_ERROR_KIND: input\npath outside workspace: {x}", True
        prompt = ("You are the reviewer. Do not modify files. Review these files (not only the diff): "
                  + ", ".join(paths) + ". List concrete bugs/risks with file:line and severity, then a "
                  "verdict (APPROVE / REQUEST_CHANGES).\n\nFocus:\n" + body)

    codex = os.environ.get("CODEX_BIN", "codex")
    codex = shutil.which(codex) or codex  # Windows: resolve codex.cmd via PATHEXT
    timeout = int(os.environ.get("CODEX_BRIDGE_TIMEOUT", "1200"))
    ok, why = preflight(codex)
    if not ok:
        kind = ("billing" if why.startswith("billing") else
                "auth" if "not logged in" in why.lower() or "login" in why.lower() else "config")
        log_call({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": tool, "sandbox": want,
                  "exit_code": None, "duration_sec": 0, "error_kind": kind,
                  "final_message": "", "stderr_tail": redact(why)})
        return (f"CODEX_ERROR_KIND: {kind}\nCodex is not usable on this runner: {redact(why)}\n"
                "The owner must run `codex login` on the runner machine."), True
    log_call({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": tool, "sandbox": want,
              "event": "started"})
    with tempfile.TemporaryDirectory() as td:
        last = Path(td) / "last.txt"
        cmd = [*([sys.executable] if codex.endswith(".py") else []), codex, "exec", "--sandbox", want, "--cd", ws, "--color", "never",
               "--output-last-message", str(last)]
        model = os.environ.get("CODEX_BRIDGE_MODEL")
        if model:
            cmd += ["--model", model]
        # The prompt goes on stdin ("-"), never on the command line: on Windows `codex`
        # resolves to codex.cmd and cmd.exe drops everything after the first newline of an
        # argument, so ROLE_PREFIX + task would arrive truncated (only the role sentence).
        cmd.append("-")
        started = time.time()
        try:
            proc = subprocess.run(cmd, cwd=ws, input=prompt, capture_output=True, env=codex_environment(),
                                  text=True, encoding="utf-8", errors="replace", timeout=timeout)
            rc, out, err = proc.returncode, proc.stdout, proc.stderr
        except FileNotFoundError:
            rc, out, err = 127, "", f"codex binary not found: {codex}"
        except subprocess.TimeoutExpired:
            rc, out, err = 124, "", f"codex timed out after {timeout}s"
        final = last.read_text(encoding="utf-8", errors="replace") if last.exists() else ""

    diffstat = subprocess.run(["git", "diff", "--stat"], cwd=ws, capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout.strip()
    kind = None if rc == 0 else (classify(err + out) or "codex_failed")
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": tool, "sandbox": want,
             "exit_code": rc, "duration_sec": round(time.time() - started, 1), "error_kind": kind,
             "final_message": redact(final)[:4000], "stderr_tail": redact(err)[-1500:]}
    log_call(entry)

    if rc != 0:
        return (f"CODEX_ERROR_KIND: {kind}\nexit_code: {rc}\n"
                f"stderr (tail):\n{redact(err)[-1500:]}\nstdout (tail):\n{redact(out)[-1000:]}"), True
    text = f"Codex ({tool}) finished OK.\n\n--- Codex final message ---\n{redact(final) or redact(out)[-4000:]}"
    if diffstat:
        text += f"\n\n--- git diff --stat ---\n{diffstat}"
    return text, False


def handle(msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:  # notification
        return None
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "codex-bridge", "version": "0.1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        if name not in TOOL_SANDBOX:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        text, is_err = run_codex(name, params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": is_err}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def setup_stdio():
    """MCP stdio is UTF-8 JSON lines. Windows pipes default to cp932, which garbles Japanese
    requests and makes writes fail on characters cp932 lacks (the reply is then lost).
    Returns the protocol output stream; sys.stdout is pointed at stderr so stray prints can
    never corrupt the protocol channel."""
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    proto = sys.stdout
    sys.stdout = sys.stderr
    return proto


def main() -> None:
    proto = setup_stdio()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            try:
                out = json.dumps(resp, ensure_ascii=False)
                out.encode("utf-8")
            except UnicodeEncodeError:  # e.g. lone surrogates: fall back to \u escapes
                out = json.dumps(resp, ensure_ascii=True)
            proto.write(out + "\n")
            proto.flush()


if __name__ == "__main__":
    main()
