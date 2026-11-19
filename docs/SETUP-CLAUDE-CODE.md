# GPT → Claude Code → Codex: setup

Architecture and security model: [ARCHITECTURE.md](ARCHITECTURE.md).
How ChatGPT submits tasks and reads results: [GPT-INSTRUCTIONS.md](GPT-INSTRUCTIONS.md).

## Two entry points

| | Queue runner (main path) | Manual workflow (kept from the scaffold) |
|---|---|---|
| Trigger | ChatGPT commits `queue/inbox/<id>.json` on `agent-queue` | GitHub → Actions → "Claude Code task (manual)" |
| Runs on | owner's PC, `python -m hub.runner loop` (outbound git only) | self-hosted runner labelled `claude-code` |
| Can edit | `implement` tasks, on branch `agent/<id>` only | no (plan mode) |
| Codex | yes, via `hub/codex_mcp_bridge.py` | not configured |

The queue runner does **not** need a GitHub Actions self-hosted runner or any open port.

## Windows one-time setup (dedicated or trusted PC)

1. Install Git, Python 3.10+, Node.js, then `npm i -g @anthropic-ai/claude-code @openai/codex`,
   and GitHub CLI (`winget install GitHub.cli`).
2. Sign in with **your own accounts** (nothing is stored in this repo):
   `claude` (log in once interactively), `codex login`, `gh auth login`.
   Git push uses the same credentials (Git Credential Manager / gh).
3. Clone this repo on a branch containing `hub/`, then:
   ```powershell
   copy config\hub.config.example.json config\hub.config.json   # review allowlists
   .\scripts\windows\check-runner.ps1
   ```
4. Create the queue branch once (pushes a new orphan branch `agent-queue` — owner approval):
   `python -m hub.admin --config config\hub.config.json init-queue`
5. Smoke test with a read-only task:
   ```powershell
   python -m hub.admin --config config\hub.config.json submit examples\task.example.json   # or let ChatGPT create it
   .\scripts\windows\start-runner.ps1 -Once
   ```
   Note: tasks submitted from the PC with plain `git` are **not** GitHub-verified; set
   `"require_verified_commit": false` for this local smoke test only, or submit via ChatGPT / github.com.
6. When satisfied, run continuously: `.\scripts\windows\start-runner.ps1`.
   Autostart at logon is optional and gated:
   `.\scripts\windows\register-autostart.ps1 -IUnderstandThisEnablesAutoRun` (only after approval).

## Guardrails (summary)
- Work only lands on `agent/<id>` branches; `main`/protected branches are refused; nothing is merged automatically.
- Claude runs `--restricted` with an allowlist; `git push`, `curl`, `gh`, `wrangler`, web access are denied.
- Codex is sandboxed to the task worktree (`read-only` for plan tasks).
- Per-run budget cap (`claude.max_budget_usd`), timeouts, retry limit, usage-limit cooldown, `queue/PAUSE` kill switch.
- My Addness repositories are not in `allowed_repos`; adding a repo is an explicit config change by the owner.
- If `claude --restricted` is unsupported by your installed version, set `"restricted": false`
  (falls back to `--setting-sources ""`), or update Claude Code.

## Tests
`python -m unittest discover -s tests -t .` — end-to-end against local bare git repos with fake
`claude`/`codex` binaries (the fake Claude still drives the real MCP bridge).
