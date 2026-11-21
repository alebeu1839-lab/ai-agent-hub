# Task addness-8c9c4a7b-ad83-4762-a7f5-f01a673fbf99: 【Claude Code PC】隔離受信ワーカーの基盤を実装・合成テスト

- **Status:** done  (attempt 1, 1897.8s)
- **Mode:** implement — repo `alebeu1839-lab/ai-agent-hub`, base `claude/funny-johnson-d34brp`
- **Work branch:** `agent/addness-8c9c4a7b-ad83-4762-a7f5-f01a673fbf99` — pushed, compare: https://github.com/alebeu1839-lab/ai-agent-hub/compare/claude/funny-johnson-d34brp...agent/addness-8c9c4a7b-ad83-4762-a7f5-f01a673fbf99
- **Codex calls:** 4 — codex_implement:ok, codex_implement:ok, codex_review:ok, codex_implement:ok
- **Finished:** 2026-11-21T10:46:07Z by `windows-main`

## Warnings
- 1 tool call(s) denied by the runner allowlist

## Claude Code report

## Summary
I added a separate worker to the Hub for My Addness, plus synthetic tests for it. The full test suite passes: **70 tests, OK**. The worker can only act on `alebeu1839-lab/-my-addness`, branch `codex/today-bulk-selection`, PR #2, and goal `afe1fa15-…`. Repo and branch must match exactly, case included. It has its own config, state folder (`state-isolated/my-addness/`), lock file, lease file, queue folders and history log, and shares none of them with the existing Hub. The existing Hub code, the example Hub config, the `My Addness` exclusion, the allowlist and the Windows scripts were not changed. No Windows scheduled task was registered. `enabled` and `execute_enabled` both default to `false`, so nothing runs until you turn them on.

What the worker refuses (fail-closed), and how it behaves:
- **Refused requests:** wrong repo, wrong branch, main, PR #3, a different PR, a different goal, a repeated run ID, another run's active lease, an unknown or mismatched HEAD, and a crash-left run with no matching checkpoint.
- **Expired leases:** never taken over automatically. Someone has to run `release-lease --run-id`.
- **Interruptions and failures:** the run is recorded as interrupted or failed, a marker comment is written back to the goal, and the lease is always released.
- **Resuming:** allowed only when the checkpoint SHA recorded in the Addness goal matches the current remote HEAD.
- **Real execution:** the executor is still a stub that refuses to run; actual work is the next stage. The command line only offers `inspect`, `dry-run`, `status` and `release-lease`.

## Changes
- `hub/isolated_worker.py` (new): config loader and checks, the gate that accepts or refuses requests, lease, process lock, state file, inspect / dry-run / process, write-back to Addness, command line
- `config/my-addness-worker.example.json` (new): example config, no secrets in it
- `tests/test_isolated_worker.py` (new): 14 synthetic tests
- `docs/ISOLATED-WORKER.md` (new): how it works, the refusal rules, and a note that the Windows schedule is not enabled at this stage
- `.gitignore`: added `state-isolated/` and `config/my-addness-worker.json`

## Codex delegation
1. `codex_implement`: first implementation of the worker. Codex had no Python available, so it ran no tests. When I ran them, one failed.
2. `codex_implement` (round 2): fixed the issues I found (below). OK.
3. `codex_review`: found two real problems (below). REQUEST_CHANGES.
4. `codex_implement` (round 3): fixed those two problems. OK.
All test runs were done by me.

## Verification
- `python -m unittest discover -s tests`: **Ran 70 tests, OK** (333 s). This includes the existing Addness intake, runner and redaction tests, so the existing Hub still behaves the same.
- `python -m unittest tests.test_isolated_worker`: **Ran 14 tests, OK**.
- What the tests cover:
  - Allowed path: inspect, dry-run, and execute with a test executor, including the done marker, a checkpoint marker with the SHA, and a progress comment on bridge goal 655c2d75.
  - Every refusal listed above.
  - Config checks: rejects main, PR 3, wildcard branches, a clone URL with embedded credentials, and a state folder that overlaps the Hub's.
  - Repeated run IDs, including two runs racing each other; a busy lock; an active lease.
  - Expired lease is left in place; manual release works only with the right run ID.
  - HEAD unknown, mismatched, or changed mid-run.
  - Interruption and resume; executor failure; inspect writes nothing.
  - The default Hub intake still skips `My Addness` tasks.
- Lease release: tests confirm the lease file is gone after success, failure and interruption.
- `git diff` shows no changes to `hub/addness_intake.py`, `hub/config.py`, `hub/runner.py`, `hub/queue.py`, `hub/addness.py`, `config/hub.config.example.json` or `scripts/windows/`.

## Review verdict
**PASS**. I read the whole diff, every fix is in, and the full suite passes on the final code.
- **Round 1** → re-delegated:
  - The test checking the state folder failed because that folder sat inside the Hub's `state/` folder.
  - Two runs with the same run ID could both get through and run twice.
  - The HEAD check would fail any real run that pushes a commit.
  - The command line accepted `release-lease` without a run ID.
- **Round 2** (Codex review) → re-delegated:
  - A run left as `running` by a crash could run again with no checkpoint.
  - The local worker config file was not gitignored, and the clone URL could contain credentials.
- **Round 3** → accepted.

## Needs owner action
- **Commit SHA:** not known yet. The runner commits and pushes branch `agent/addness-8c9c4a7b-…`; please record the SHA from the runner's result.
- **Addness write-back:** the result is written back to this goal by the runner. I did not write progress to the original task `afe1fa15` or to bridge `655c2d75`, because the Hub runner has no write path for those. Please post a progress note there yourself, or ask for it in a separate task.
- **Next step (separate task, needs your approval):**
  1. Create `config/my-addness-worker.json` on the PC.
  2. Run `python -m hub.isolated_worker inspect --run-id <id> --repo alebeu1839-lab/-my-addness --branch codex/today-bulk-selection --pr 2 --goal afe1fa15-e2d2-41fc-a6c0-86b8a9eefcf2`. It only reads; it writes nothing.
  3. Check that the real HEAD and the checkpoints line up.
  4. Then build the inspect-resume executor.
- Turning on the dedicated Windows schedule and setting `execute_enabled` stay separate steps after that. Merging to main is not part of this work.

## Diffstat
```
.gitignore                            |   2 +
 config/my-addness-worker.example.json |  23 ++
 docs/ISOLATED-WORKER.md               |  18 ++
 hub/isolated_worker.py                | 551 ++++++++++++++++++++++++++++++++++
 tests/test_isolated_worker.py         | 281 +++++++++++++++++
 5 files changed, 875 insertions(+)
```

_This branch is not merged anywhere. Review it and open a PR manually if acceptable._
