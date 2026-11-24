# AI Agent Hub: durable execution prototype

Status: **prototype only**, not deployed. This is not an active Claude Code/Codex or Addness integration.

## Goal
GPT -> Addness -> Hub queue -> Claude Code (orchestrator/reviewer) -> Codex (implement/test) -> GitHub -> Addness.

## Run
Python 3 standard library only. Set up a local JSON queue and trusted command config:
```json
{"tasks":[{"id":"goal-001","state":"pending","depends_on":[],"max_attempts":2}]}
```
```json
{"implement":["python","path/to/trusted_codex_adapter.py"],"review":["python","path/to/trusted_claude_adapter.py"]}
```
Then: `python agent_queue.py --queue queue.json --config commands.json`.
Commands are **operator configured**, not sourced from task payload. Worker appends task ID as a single argument.
No real agent adapters are included; do not enable with placeholder commands.

## Safety
- Dedicated branch only; never update My Addness, production, main or PR #3.
- In-flight work found after a crash goes to waiting_approval: verify side effects before retrying.
- External publishing, billing, contracts, migrations and destructive actions require explicit approval.
- No simultaneous worker processes: add a single-instance lock before production.
- A failed task can retry on the next invocation until max_attempts; there is no daemon scheduler yet.
- Addness read/write, usage-limit detection, model fallback, idempotency keys, security review, subprocess sandbox, logs and audit retention are **not implemented**.

## Acceptance before enabling automation
Implement a real local Claude/Codex adapter, credential handling, single-writer lock, Addness synchronization, bounded retries/backoff, restart test, 3 consecutive child goals, test evidence, and explicit user approval for production deployment.

## Third-party options to evaluate (do not auto-install)
- https://github.com/kastrah/orchestrator
- https://github.com/dsifry/metaswarm
- https://github.com/open-mercato/cezar

Prefer reusing audited components over inventing a second orchestration layer. Verify licenses and Windows compatibility before adoption.
