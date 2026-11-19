#!/usr/bin/env python3
"""Stand-in for `codex exec` used in tests (no OpenAI account needed).

Behaviour is selected by FAKE_CODEX_MODE: ok (default) | usage_limit | auth.
In ok mode it writes CODEX_WAS_HERE.md in --cd dir (only when sandbox allows writes).
"""
import os, sys
args = sys.argv[1:]
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
if args[:2] == ["login", "status"]:
    if mode == "auth":
        print("Not logged in"); sys.exit(1)
    if mode == "apikey" or "OPENAI_API_KEY" in os.environ:
        print("Logged in using an API key - sk-proj-***"); sys.exit(0)
    print("Logged in using ChatGPT"); sys.exit(0)
assert args and args[0] == "exec", args
def opt(name):
    return args[args.index(name) + 1] if name in args else None
cd, sandbox, last = opt("--cd"), opt("--sandbox"), opt("--output-last-message")
assert sandbox in ("read-only", "workspace-write"), sandbox
assert "--dangerously-bypass-approvals-and-sandbox" not in args
assert "OPENAI_API_KEY" not in os.environ, "API key leaked into codex exec env"
if mode == "usage_limit":
    print("ERROR: You've hit your usage limit. Try again later.", file=sys.stderr); sys.exit(1)
if mode == "auth":
    print("Error: Not logged in. Run `codex login`.", file=sys.stderr); sys.exit(1)
import time; time.sleep(int(os.environ.get("FAKE_CODEX_SLEEP", "0")))
prompt = args[-1]
if sandbox == "workspace-write":
    with open(os.path.join(cd, "CODEX_WAS_HERE.md"), "w") as f:
        f.write("# Written by fake Codex\n\n" + prompt.splitlines()[-1][:200] + "\n")
    msg = "Implemented: created CODEX_WAS_HERE.md. Verified by reading the file back."
else:
    msg = "Review: no blocking issues found. VERDICT: APPROVE"
open(last, "w").write(msg)
print("fake codex done")
