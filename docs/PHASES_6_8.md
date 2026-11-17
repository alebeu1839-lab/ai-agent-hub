# Phases 6–8: implementation record

## Phase 6 — Provider adapter boundary
`hub/providers.py` introduces explicit capability registration for GPT, Claude Code and Codex. **All three are disabled by default**. Only manually registered mock handlers can run. ChatGPT subscriptions are not API credentials; account-specific access and additional billing/authorization require separate verification.

## Phase 7 — Company organization
`hub/organization.py` provides deterministic CEO planning for two **offline sandbox** scenarios. Tasks are split among sales, production, QA and administration, with dependencies and idempotency. This is a rule-based simulation; **it does not autonomously reason as GPT**, discover CrowdWorks jobs or communicate with customers.

## Phase 8 — Dashboard and acceptance scenario
`hub/dashboard.py` generates a static read-only local HTML snapshot. `hub/demo.py` simulates all four departments and their dependency chain.

Run in Python 3.10+ from repository root:

```bash
python -m unittest discover -s tests -v
python -m hub.demo --html ./demo-status.html
```

The HTML file is **local only** and does not publish or expose an endpoint.

## Release blockers
- Run complete test suite in CI and investigate failures; verify branch protections and project structure.
- Create real GPT/Codex/Claude Code adapters after explicit credentials, terms, cost and authorization validation; do **not** automatically use the ChatGPT UI as an API.
- Add durable authenticated approval records, non-replayable authorization and permitted external operations. Currently all external operations are blocked.
- Repair distributed execution leases and hung worker shutdown; current internal prototype cannot kill a stuck thread.
- Add authentication, privacy, access control, and secure deployment before any networked management dashboard.
- Test production-like crash recovery, budget caps, provider rates, and multi-process concurrency; obtain operator signoff before going live.

**No live external AI integrations, CrowdWorks actions, payments, deployment or background schedules were enabled.**
