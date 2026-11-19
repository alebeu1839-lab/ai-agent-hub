# My Addness × AI Agent Hub integration plan

## Target architecture
Owner (phone) → My Addness (goals/status/approvals) ↔ GPT (planning) → AI Agent Hub (durable queue / security / execution) → Claude Code (orchestration) → Codex (implementation/test/review) → git branch + structured results → My Addness.

My Addness is BOTH a future dashboard and a target repository; it must not be a required dependency for the runner itself.

## Verified starting point (2026-11-19)
- My Addness repository: `alebeu1839-lab/-my-addness`, **private**.
- AI Agent Hub repository `alebeu1839-lab/ai-development-hub` is **public**, including the `agent-queue` branch and result reports.
- Current runner allowlist ONLY allows `alebeu1839-lab/ai-development-hub`.
- Cloud smoke test completed with Claude; Codex authorization failed (not logged in). `20261119-windows-01` remains in queue.
- Therefore **DO NOT add the private My Addness repo to this public queue as-is**. Task descriptions, patch summaries, and results could disclose private code or business data.

## Safe dependency order
1. **Fix Codex authorization on Windows**; run `codex login status`, `codex_test`, `codex_review`, verify successful entries in result.json.
2. **Make task/result storage private** before allowing My Addness tasks. Options:
   - Preferred: separate private GitHub queue repository with least-privilege access, and point runner `queue_repo_url` there, OR
   - change the hub repository to private (requires owner approval).
   Do not assume moving only My Addness to private resolves leakage.
3. **Update local, gitignored `config/hub.config.json`** only after private queue exists, preserving current settings and adding:
   ```json
   "alebeu1839-lab/-my-addness": {
     "clone_url": "https://github.com/alebeu1839-lab/-my-addness.git",
     "allowed_base_branches": ["codex/*", "claude/*", "chore/*"]
   }
   ```
   Avoid `main`, any friend-edition branch and any production release branch. Review specific base branches before task dispatch. Do not automatically publish, deploy, merge or migrate D1.
4. **Plan-only test**: read-only review of current branch, tests, migration count, existing CI and release gates. Log redacted status privately.
5. **Implementation smoke test**: a tiny non-production test change on `agent/<task-id>`, with successful Codex test/review and regression tests. No merge without owner approval.
6. **My Addness dashboard**: a read-only integration first (task id, project, stage, assigned executor, start/last update, result link, error, approval required). Then authenticated task submission and approvals after security review.
7. **Resilience**: runner keeps its state outside My Addness; UI unavailability cannot lose or block queued work. Queue supports PAUSE, idempotency, lease expiry and cooldown/backoff.

## No-go boundaries
- Never put My Addness source, sensitive design notes, private task instructions, credentials or outputs in the public hub repository/queue.
- Do not edit `main`, friend-edition PR #3, production app, or D1 migration without separate explicit authorization.
- No paid API fallback, no extra-usage charges, no unattended deployment.
- A task marked `done` is not proof of successful Codex participation: check each `codex_calls` status.

## Acceptance criteria
- Private queue verified, private My Addness repository access confirmed on Windows.
- Plan and implementation tasks accepted by allowlist; invalid repos and protected branches rejected.
- Claude → Codex real Windows invocation succeeds, with independent review recorded.
- Results can be displayed from My Addness without exposing private data publicly.
- Operator can pause, resume, requeue, and see last verified action from a phone.
