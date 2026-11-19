# GPT → Claude Code → Codex: staged setup

## Current state
This branch adds a **manual test entry point**, not an always-on connection. Nothing runs until this workflow is merged into a branch GitHub can dispatch, a dedicated Windows runner is online, and Claude Code is installed and authenticated there.

## Windows one-time setup (on a dedicated machine)
1. Install Git, Node.js, Claude Code CLI, and Codex CLI following their official documentation. Sign in to each tool with your own account. Do not store API keys in repository files or issue comments.
2. GitHub repository → Settings → Actions → Runners → New self-hosted runner. Follow GitHub's Windows installation instructions, then attach the custom label `claude-code`. **Only use this runner for trusted repositories.** Public-repository self-hosted runners must be isolated and tightly controlled; a private dedicated repository is safer.
3. In PowerShell, verify `claude --version` and `codex --version`. Configure Codex as a Claude Code MCP server on the runner if desired and verify it from the Claude Code session.
4. Review the workflow and merge it only after the runner is isolated, repository access is restricted, and you approve enabling task execution.
5. GitHub → Actions → “Claude Code task (manual)” → Run workflow, choose a **non-production branch**, and enter a harmless read-only task, such as “Inspect the repository and propose a test plan; do not edit files.”

## Guardrails
- Workflow is intentionally **plan mode**: it can analyze, but is not authorized to modify files or deploy.
- It does not run on push, issue, pull request, or on an automatic schedule.
- It does not export your GitHub token to the CLI or persist checkout credentials.
- No direct access to My Addness production, Cloudflare, D1, or `main` is granted.
- Enabling edits, autonomous routing, or a GPT-triggered queue requires a separate reviewed PR, restricted credentials, test gates, and explicit deployment approval.
- Completion evidence: successful Actions run URL, Claude CLI response, and confirmed runner status.

## Architecture target
ChatGPT (task planning) → safe task queue / reviewed dispatch → Windows runner → Claude Code → Codex via MCP → GitHub branch / PR → ChatGPT reports results.

The present ChatGPT connector can edit GitHub files, but cannot directly start a local Windows process or call Claude Code. Do not report the bridge as live until an actual run succeeds.
