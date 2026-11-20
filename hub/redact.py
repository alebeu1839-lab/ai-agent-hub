"""Redact secrets before anything is written to logs or pushed to GitHub."""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"),            # JWTs
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),            # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),             # Anthropic keys
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),       # OpenAI keys
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),              # AWS access key ids
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),                 # Google API keys
    re.compile(r"[sr]k_(?:live|test)_[0-9A-Za-z]{10,}"),   # Stripe keys
    re.compile(r"npm_[A-Za-z0-9]{30,}"),                   # npm tokens
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),          # Slack tokens
    re.compile(r"(?i)(authorization:\s*(?:bearer|token|basic)\s+)[^\s\"']+"),
    re.compile(r"(?i)((?:api[_-]?key|secret|password|passwd|token)[\"']?\s*[=:]\s*[\"']?)[^\s\"']{6,}"),
    re.compile(r"[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@"),  # creds embedded in URLs
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pat in _PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + "[REDACTED]", out)
        else:
            out = pat.sub("[REDACTED]", out)
    return out
