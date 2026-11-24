"""Thin git wrapper. Credentials come from the machine's git credential helper, never from code."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def git(args: list[str], cwd: str | Path | None = None, check: bool = True,
        timeout: int = 300) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")  # never hang waiting for a password
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])} failed: {proc.stderr.strip()[:500]}")
    return proc


def ensure_identity(cwd: str | Path) -> None:
    if not git(["config", "user.email"], cwd, check=False).stdout.strip():
        git(["config", "user.email", "agent-hub@localhost"], cwd)
    if not git(["config", "user.name"], cwd, check=False).stdout.strip():
        git(["config", "user.name", "AI Agent Hub Runner"], cwd)
