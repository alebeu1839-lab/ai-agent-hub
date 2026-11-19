#!/usr/bin/env python3
"""Stand-in for `claude -p` used in unit tests.

It really starts the MCP server from --mcp-config (the codex bridge), performs the MCP
handshake and calls a tool, so the Claude->Codex wiring is exercised end to end.
FAKE_CLAUDE_MODE: delegate (default) | rate_limit | crash
"""
import json, os, subprocess, sys, uuid
args = sys.argv[1:]
mode = os.environ.get("FAKE_CLAUDE_MODE", "delegate")
if mode == "rate_limit":
    print("API Error: 429 rate limit exceeded", file=sys.stderr); sys.exit(1)
if mode == "crash":
    print("something fatal", file=sys.stderr); sys.exit(2)
assert "--strict-mcp-config" in args
cfg = json.load(open(args[args.index("--mcp-config") + 1]))
srv = cfg["mcpServers"]["codex"]
settings = json.load(open(args[args.index("--settings") + 1]))
allowed = settings["permissions"]["allow"]
assert "Bash(git push:*)" in settings["permissions"]["deny"]
assert "--restricted" in args
prompt = sys.stdin.read()
assert prompt.strip(), "prompt must arrive on stdin"
tool = "codex_implement" if "mcp__codex__codex_implement" in allowed else "codex_review"
env = {**os.environ, **srv["env"]}
p = subprocess.Popen([srv["command"], *srv["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
def rpc(i, method, params=None):
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())
rpc(1, "initialize", {"protocolVersion": "2025-06-18"})
tools = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
r = rpc(3, "tools/call", {"name": tool, "arguments": {"instructions": "add marker file"}})["result"]
p.stdin.close(); p.wait()
text = r["content"][0]["text"]
out = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
       "session_id": str(uuid.uuid4()), "total_cost_usd": 0.0,
       "result": f"## Summary\nfake claude delegated {tool} (tools seen: {tools})\n## Codex delegation\n{text}\n"}
print(json.dumps(out))
