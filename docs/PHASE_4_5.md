# Phase 4–5: rate-limit recovery and internal parallel work

Status: **prototype implementation, not production-ready**.

- `hub/parallel.py`: Bounded thread pool (1–8 workers). SQLite state transitions occur only on the caller thread, not worker threads. Assignment uses the existing persistent lease table; each worker result moves to **reviewing**, never directly to delivered/completed. Unknown departments are skipped.
- `hub/orchestrator.py`: One explicit scheduler tick: due retry -> queued -> internal parallel execution -> schedule rate-limited tasks. It does not run automatically in the background.
- `tests/test_phase45.py`: Mock-only regression tests covering parallel dispatch, unmapped department, 429/retry/recovery, malformed outputs, and bounds.

## Important safety boundaries
- **Only trusted, internal mock workers.** No external API or Claude/Codex integration.
- Expired leases are intentionally not automatically stolen: processes might still be executing. Incident/reconciliation tooling is required before production multi-process deployment.
- A worker running indefinitely can still stall a tick: thread executor has no hard kill. Add an isolatable subprocess/remote worker with enforceable timeout before live work.
- The existing `ControlPlane` and `RetryPlanner` are not a production transactional scheduler. More SQLite concurrency/race testing and a durable approval ledger are required.
- `RetryPlanner` requeues **internal** work only; external submission/payment/email replay remains forbidden.
- Test command: `python -m unittest discover -s tests -v`. GitHub Actions confirmation must be checked separately.
