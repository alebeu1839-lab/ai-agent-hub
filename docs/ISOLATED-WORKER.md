# Isolated My Addness worker

This is a separate, disabled-by-default foundation for the My Addness repository. It owns its config and state under `state-isolated/my-addness`; it does not use the default hub queue or enable intake. Execution is library-only and requires an injected executor.

Copy `config/my-addness-worker.example.json` to `config/my-addness-worker.json`. Keep `enabled` and `execute_enabled` false until explicitly configured. The worker validates the fixed repository, branch, PR, source goal and isolated state path. Addness client settings are nested in this config; do not put credentials in it.

Commands:

```powershell
python -m hub.isolated_worker --config config/my-addness-worker.json inspect --run-id run-001 --repo alebeu1839-lab/-my-addness --branch codex/today-bulk-selection --pr 2 --goal afe1fa15-e2d2-41fc-a6c0-86b8a9eefcf2
python -m hub.isolated_worker --config config/my-addness-worker.json dry-run --run-id run-001 --repo alebeu1839-lab/-my-addness --branch codex/today-bulk-selection --pr 2 --goal afe1fa15-e2d2-41fc-a6c0-86b8a9eefcf2
python -m hub.isolated_worker --config config/my-addness-worker.json status
python -m hub.isolated_worker --config config/my-addness-worker.json release-lease --run-id run-001
```

Fail-closed rules: invalid or mismatched repo/branch/PR/goal, unknown remote HEAD, stale/corrupt lease, duplicate run ID, and mismatched resume checkpoint stop processing. Expired leases and stale process locks require manual operator action; neither is removed automatically. `inspect` is read-only. There is no execute CLI command in this stage.

**Windows schedule is NOT enabled in this stage.**
