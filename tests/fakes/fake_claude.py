#!/usr/bin/env python3
"""Stand-in for `claude -p` used in unit tests.

It really starts the MCP server from --mcp-config (the codex bridge), performs the MCP
handshake and calls a tool, so the Claude->Codex wiring is exercised end to end.
FAKE_CLAUDE_MODE: delegate (default) | rate_limit | crash
"""
import json, os, subprocess, sys, uuid
args = sys.argv[1:]
mode = os.environ.get("FAKE_CLAUDE_MODE", "delegate")
if args[:2] == ["auth", "status"]:
    auth = os.environ.get("FAKE_CLAUDE_AUTH", "oauth_token")
    if "ANTHROPIC_API_KEY" in os.environ:
        auth = "api_key"  # what the real CLI would do: a key in env wins over the subscription
    print(json.dumps({"loggedIn": True, "authMethod": auth, "apiProvider": "firstParty"})); sys.exit(0)
assert "ANTHROPIC_API_KEY" not in os.environ, "API key leaked into claude -p env"
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
implement = "mcp__codex__codex_implement" in allowed
env = {**os.environ, **srv["env"]}
p = subprocess.Popen([srv["command"], *srv["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
def rpc(i, method, params=None):
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())
rpc(1, "initialize", {"protocolVersion": "2025-06-18"})
tools = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
def call(i, name, args):
    return rpc(i, "tools/call", {"name": name, "arguments": args})["result"]["content"][0]["text"]
rounds, texts, verdict, i = [], [], "FAIL", 10
if implement:
    instructions = "add marker file"
    for rnd in range(1, 4):  # the review gate the orchestrator prompt requires
        texts.append(call(i, "codex_implement", {"instructions": instructions})); i += 1
        review = call(i, "codex_review", {}); i += 1
        texts.append(review)
        if "VERDICT: APPROVE" in review:
            rounds.append(f"round {rnd}: approved"); verdict = "PASS"; break
        rounds.append(f"round {rnd}: changes requested -> re-delegated")
        instructions = "address review: " + review
    tool = "codex_implement"
else:
    texts.append(call(i, "codex_review", {"paths": ["README.md"]})); tool = "codex_review"; verdict = "PASS"
    rounds.append("plan review")
p.stdin.close(); p.wait()
text = "\n".join(texts)
out = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
       "session_id": str(uuid.uuid4()), "total_cost_usd": 0.0,
       "result": (f"## Summary\nfake claude delegated {tool} (tools seen: {tools})\n"
                  f"## Codex delegation\n{text}\n## Verification\nfake: read CODEX_WAS_HERE.md back\n"
                  f"## Review verdict\n{verdict}\n" + "\n".join(rounds) + "\n## Needs owner action\nnone\n")}
print(json.dumps(out))
