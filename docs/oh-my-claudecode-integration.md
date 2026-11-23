# oh-my-claudecode integration proposal (opt-in)

Upstream: https://github.com/Yeachan-Heo/oh-my-claudecode
License reported by upstream: MIT. Check current release, dependencies and security advisory before installation.

## Ownership of responsibilities
- Addness: source of truth for parent/child goals, completion evidence and approvals.
- AI Agent Hub: durable FIFO/dependency queue, leases, deduplication, retry, audit, recovery, cross-goal continuation.
- Claude Code + oh-my-claudecode (OMC): within-task planning, team execution, review and fix.
- Codex CLI: implementation/test or independent review as assigned by Claude/OMC.
- GitHub: code, pull requests, CI and proof.

**Do not operate both Hub and OMC as competing schedulers for the same task.** Hub dispatches exactly one child-goal execution to OMC; OMC manages subtasks within that assignment. OMC returns a machine-readable result, test evidence and commit/PR refs, then Hub decides whether to mark it complete and advance to the next child goal.

## Installation: Windows, user-mediated and NOT yet executed
Preflight in a trusted local Claude Code environment:
1. Check `claude --version`, `codex --version`, `node --version`, and existing Claude plugin/MCP configs.
2. Check whether `omc` is already installed; if so inspect configuration before adding anything.
3. OMC team mode requires tmux; Windows official docs recommend psmux (`winget install psmux`) or WSL tmux. Node 22+ preferred.
4. Confirm install scope (user or dedicated project); keep My Addness production and other repos unchanged.

The official Claude Code marketplace method (run one slash command per line **inside Claude Code**):
```text
/plugin marketplace add https://github.com/Yeachan-Heo/oh-my-claudecode
/plugin install oh-my-claudecode
/omc-setup
```
Do not execute the above via generic shell or silently on the user's workstation.
Alternative CLI package documented upstream: `oh-my-claude-sisyphus`.
OMC 4.4+ changed Codex integration: use CLI Team mode (`omc team N:codex "..."`), rather than assuming an older Codex MCP server.

## Required integration contract
Hub sends task ID, exact repo/branch, goal acceptance criteria, dependencies, forbidden targets and review policy.
OMC executes only within an isolated worktree/branch and returns `{task_id, status, commit, pr_url, tests, reviewer, evidence}`.
Hub verifies return schema, idempotency token, branch allowlist, and that tests/commits exist; fail closed on unverifiable completion.
On provider usage limits, stop spawning; store blocked state and retry after real availability. If both providers are unavailable, pause with state persisted.
On process crash, inspect existing changes before retrying to avoid duplicated writes.
Never auto-approve billing, contracts, deployment, data migration, external publishing or destructive changes.

## Acceptance tests before activation
- Baseline Windows installation, plugin conflict and auth checks
- Claude orchestrates Codex implementation plus independent review on a disposable demo repo
- Exactly three child tasks finish sequentially, each with independent test evidence
- Crash/restart and simulated rate-limit resume without duplicate commits
- Addness state sync and child-goal completion validation
- No writes to My Addness main, friend PR #3, production sites, or unrelated repositories

Status: upstream evaluated; integration design documented. **No plugin installed, no worker launched, no production automation activated.**
