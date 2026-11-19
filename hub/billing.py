"""Subscription-only guard: never let the runner incur pay-as-you-go API charges.

* Claude Code must be signed in with a subscription login (OAuth), checked with
  `claude auth status --json`. API keys, apiKeyHelper, Bedrock/Vertex/Foundry are refused.
* Codex must be signed in with a ChatGPT account (`codex login status`), not an API key.
* API-key environment variables are removed from every child process, so a stray key on
  the machine can never switch the CLIs to metered billing.
If a check fails, the runner does not pick up tasks (fail closed) and records why.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

# Env vars that would make a CLI bill an API account instead of the subscription.
PAID_ENV_VARS = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "AWS_BEARER_TOKEN_BEDROCK", "OPENAI_API_KEY", "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
)
DEFAULT_CLAUDE_AUTH = ["oauth_token", "oauth", "claude.ai", "claudeai", "subscription"]


def subscription_env(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    for k in PAID_ENV_VARS:
        env.pop(k, None)
    return env


def check_claude(bin_name: str, allowed_methods: list[str] | None = None) -> tuple[bool, str]:
    allowed = [m.lower() for m in (allowed_methods or DEFAULT_CLAUDE_AUTH)]
    exe = shutil.which(bin_name) or bin_name
    try:
        p = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, env=subscription_env(),
                           stdin=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, f"claude auth status failed: {e}"
    try:
        info = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return False, "claude auth status did not return JSON (update Claude Code)"
    method = str(info.get("authMethod", "")).lower()
    provider = str(info.get("apiProvider", "firstParty"))
    if not info.get("loggedIn"):
        return False, "Claude Code is not logged in (run `claude` and sign in with your subscription)"
    if provider != "firstParty":
        return False, f"Claude Code uses provider {provider!r} (metered); subscription required"
    if method not in allowed:
        return False, (f"Claude Code auth method {method!r} is not an allowed subscription login "
                       f"{allowed}; refusing to avoid API charges")
    return True, f"claude: {method}"


def check_codex(bin_name: str) -> tuple[bool, str]:
    exe = shutil.which(bin_name) or bin_name
    try:
        p = subprocess.run([exe, "login", "status"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, env=subscription_env(), stdin=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, f"codex login status failed: {e}"
    out = (p.stdout + p.stderr).strip()
    if p.returncode != 0:
        return False, f"Codex not logged in: {out[-200:]}"
    if "api key" in out.lower() or "chatgpt" not in out.lower():
        return False, f"Codex must use a ChatGPT login, not an API key: {out[-200:]}"
    return True, "codex: ChatGPT login"
