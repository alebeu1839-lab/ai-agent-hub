# AI Agent Hub — GPT → Claude Code → Codex dispatch

## Flow

```
ChatGPT (planner, phone)
   │  GitHub connector: commit queue/inbox/<id>.json on branch `agent-queue`
   ▼
GitHub repo (queue branch = data only)            ◄──── results/<id>/report.md (GPT reads)
   ▲   │  git fetch (outbound only, no open ports)
   │   ▼
Runner on the owner's Windows PC  (python -m hub.runner loop)
   │  validate + authorise → claim (commit to running/) → clone into state/work/<id>
   ▼
Claude Code  (claude -p --restricted, tool allowlist, budget cap)
   │  MCP stdio: hub/codex_mcp_bridge.py
   ▼
Codex CLI  (codex exec --sandbox workspace-write|read-only --cd <worktree>)
   │  codex_implement / codex_test / codex_review
   ▼
Claude Code integrates + writes final report
   ▼
Runner: commit worktree → push branch agent/<id> → write results → move task to done/failed
```

## Components

| File | Role |
|---|---|
| `hub/runner.py` | Poll loop, authorisation, claim/lease, workspace, retry/backoff, cooldown, reporting |
| `hub/queue.py` | Git-backed queue with optimistic locking (push race → reset + retry) |
| `hub/config.py` | Config defaults + **task validation** (allowlists, size, fields) |
| `hub/claude_exec.py` | Builds the `claude -p` invocation (settings file, MCP config, restricted mode) |
| `hub/codex_mcp_bridge.py` | MCP server exposing Codex as 3 tools; sandbox cap, timeout, preflight, call log |
| `hub/redact.py` | Strips tokens/keys/passwords before anything is logged or pushed |
| `hub/admin.py` | `init-queue`, `submit`, `pause`, `resume`, `requeue` |
| `prompts/claude-orchestrator.md` | Claude's role, delegation flow, hard rules, report format |
| `scripts/windows/*.ps1` | Prerequisite check, start runner, optional autostart (gated) |
| `.github/workflows/claude-code.yml` | Existing manual, plan-only entry point (kept as-is) |

### Why a custom Codex MCP bridge
Codex CLI 0.170 (tested) has no `codex mcp-server` subcommand any more. Wrapping
`codex exec` also lets the runner enforce limits the model cannot override: fixed
working directory, sandbox ceiling per task mode, never `danger-full-access` or bypass
flags, a hard timeout, and a JSONL log of every call that the runner puts in the report.

## Security model

1. **Who can submit** — only someone who can push to the queue branch (keep the repo
   private and collaborators minimal). With `security.verify_submitter=true` the runner also
   asks the GitHub API (`gh api`) for the author login of the commit that last touched the
   task file and requires it to be in `allowed_submitters`. Fail-closed: if `gh` is missing
   or the check errors, the task is rejected.
   *Tested 2026-11-19:* a commit created through the GitHub API (the same path a ChatGPT
   GitHub connector uses) is attributed to the owner's login but is **unsigned**
   (`verification.reason = "unsigned"`). Requiring signatures (`require_signed_commit=true`)
   would therefore reject connector submissions; it is off by default. The login check is
   not a cryptographic guarantee — anyone with push access can forge an author e-mail —
   so repository write access is the real trust boundary.
2. **What can be asked** — tasks are JSON data, never code. Unknown fields are rejected.
   `repo` must be allow-listed, `base_branch` must match the repo's patterns, `mode` must
   be enabled on the runner (`plan` read-only / `implement`), instructions ≤ 8000 chars.
   My Addness repositories are **not** in the allowlist.
3. **What Claude can do** — `--restricted` (ignores user/project settings, confines file
   tools to the worktree, refuses bypassPermissions) + explicit allow rules: read tools,
   `git status/diff/log/show`, and in implement mode Edit/Write/`git add`/test runners.
   Denied: `git push`, `git remote`, `curl`, `wget`, `gh`, `wrangler`, WebFetch/WebSearch,
   `rm -rf`. Everything else is denied automatically in `-p` mode (recorded as
   `permission_denials` in the report). `--max-budget-usd` caps spend per run.
4. **What Codex can do** — `workspace-write` sandbox only inside the worktree for
   implement tasks, `read-only` for plan tasks (the bridge refuses write tools).
5. **What gets pushed** — only the runner pushes, only to `agent/<task-id>`; protected
   patterns (`main`, `master`, `production`, `release/*`, `gh-pages`) are refused. Nothing
   is merged; a human opens/merges PRs.
6. **Secrets** — none in repo, config or task files. CLIs use the machine's own logins
   (`claude`, `codex login`, git credential manager / `gh auth`). Logs, reports and Codex
   call logs pass through `redact()` before being written or pushed.

## Billing: subscription only (owner rule: no extra charges)

`hub/billing.py`, checked before any task is claimed (fail closed, task stays in inbox):

* Claude Code must report `loggedIn` with a subscription OAuth `authMethod` and
  `apiProvider = firstParty` (`claude auth status --json`). API key / apiKeyHelper /
  Bedrock / Vertex / Foundry → runner status `blocked: …`, nothing runs.
* Codex must report a **ChatGPT** login (`codex login status`); API-key login is refused.
* `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `CODEX_API_KEY`, Bedrock/Vertex
  switches are stripped from every child process, so a key on the machine cannot switch
  either CLI to metered billing.
* Subscription usage limits → cooldown and retry later; never fall back to a paid path.
* Not controllable from code: the account-level **"extra usage" / pay-as-you-go overage**
  settings on claude.ai and chatgpt.com. Keep them **OFF**.
* `total_cost_usd` in reports is a list-price estimate from Claude Code, not a charge,
  when running on a subscription.

## Reliability

| Situation | Behaviour |
|---|---|
| Rate limit / network / 5xx / timeout from Claude | task back to `inbox/` with exponential `not_before`, `attempts+1`; `failed/` after `max_attempts` |
| Usage limit (Claude) | as above + runner-wide cooldown (`state/cooldown_until`, default 30 min) |
| Codex usage limit / auth / network | bridge returns `CODEX_ERROR_KIND: …` fast; Claude continues or reports; report shows warnings |
| Codex not logged in | preflight `codex login status` fails in < 1 s instead of hanging |
| Long Codex runs | runner sets `MCP_TOOL_TIMEOUT` = codex timeout + 120 s (Claude's default is ~60 s) |
| Runner crash / PC reboot | task stays in `running/` with `runner=<id>`; on restart the runner resumes its own tasks first, reusing the worktree and `claude --resume <session_id>` |
| Partial progress | every attempt ends with a checkpoint commit + push of `agent/<id>`; next attempt starts from that branch |
| Two runners | claim is a git push; the loser sees the task gone and skips it |
| Emergency stop | create `queue/PAUSE` (GPT can do it) or `python -m hub.admin pause` |
| Invalid / unauthorised task | moved to `failed/` with a `REJECTED` report; never executed |

## Records

* GitHub (queue branch): `queue/status.md`, `queue/results/<id>/{report.md,result.json,codex_calls.jsonl}`,
  full state history in git log.
* Local (`state/`, gitignored): `history.jsonl` (every event), `logs/runner.log`,
  `runs/<id>/attempt-N/` (Claude JSON output, MCP config, settings, Codex call log), `work/<id>/` worktrees.
