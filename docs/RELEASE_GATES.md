# Release gate: AI Agent Hub (2026-11-17)

## What has actually been built
- SQLite task ledger and event history
- Internal worker dispatch and mock-only parallel execution
- Retry planning and non-replaying quarantine for stale worker leases
- Simple project budget counters, role rules and task dependencies
- Three disabled-by-default provider entries: GPT, Claude Code, Codex
- Opt-in local CLI bridge skeleton with fixed-command enforcement
- Deterministic mock CEO -> four departments delegation
- Offline read-only HTML dashboard generator and sandbox demo

## Verification evidence
- Source files and test files saved to GitHub development branch.
- GitHub Actions workflow exists, but CI run success was **not confirmed** in this session.
- CLI adapter command signatures have not been checked against the installed vendor CLI versions.
- No real AI provider connection, CrowdWorks operation or production deployment was exercised.

## Hard release blockers
- [ ] Run entire test suite and repair any failing tests; attach full CI logs and green check
- [ ] Inspect current installed Codex CLI and Claude Code versions and supported noninteractive flags
- [ ] Confirm environment, secrets handling, access rights, provider quotas and cost ceiling
- [ ] Persist output artifacts before reporting actual completion
- [ ] Establish durable user-authenticated external-action approval; current external actions remain disabled
- [ ] Add enforceable worker hard timeout, safe shutdown, multi-process ownership, crash recovery tests
- [ ] Validate per-provider cost and rate controls without violating terms or bypassing caps
- [ ] Deploy only after explicit authorization with authentication, backups, privacy isolation and monitoring
- [ ] Integrate CrowdWorks system as a separate repository with sandbox E2E tests and case-by-case permission checks
- [ ] Verify end-to-end: owner input -> CEO -> manager -> actual authorized AI worker -> QA -> report

## Owner permissions
- Authorized now: internal design, code edits on development branch, tests, sandbox/mock work
- Requires separate consent: API billing, contracts, public deployment, external message or application submission, data sharing

## Completion definition
Do **not** mark the AI company as autonomous or production-ready until all hard gates
are evidenced. Record each test result separately: not_run / pass / fail.
