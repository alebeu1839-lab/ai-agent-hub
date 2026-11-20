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

**Quick path:** paste this into PowerShell (normal user). It does steps 1–5 below and processes one task:
```powershell
irm https://raw.githubusercontent.com/alebeu1839-lab/ai-agent-hub/feat/claude-code-dispatch/scripts/windows/bootstrap.ps1 | iex
```

Manual steps:

1. Install Git, Python 3.10+, Node.js, then `npm i -g @anthropic-ai/claude-code @openai/codex`,
   and GitHub CLI (`winget install GitHub.cli`).
2. Sign in with **your own subscription accounts** (nothing is stored in this repo):
   `claude` → choose the Claude subscription (Pro/Max) login, **not** an API key;
   `codex login` → "Sign in with ChatGPT", **not** an API key; `gh auth login`.
   Do not set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. Turn **extra usage / overage OFF** in your
   Claude and ChatGPT account settings. The runner refuses to run otherwise (`blocked: …`).
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
   Note: the runner checks (via `gh api`) that the commit adding the task was authored by a login in
   `allowed_submitters`. A local `git` commit only maps to your login if its e-mail is one of your
   GitHub e-mails; otherwise submit via ChatGPT / github.com, or set `"verify_submitter": false` for this smoke test.
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
