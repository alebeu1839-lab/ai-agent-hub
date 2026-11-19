# Task demo-20261119-01: Review redact.py (GitHub round-trip demo)

- **Status:** done  (attempt 1, 23.6s)
- **Mode:** plan — repo `alebeu1839-lab/ai-development-hub`, base `claude/beautiful-bohr-40e17o`
- **Work branch:** `agent/demo-20261119-01` (not pushed)
- **Codex calls:** 1 — codex_review:ok
- **Finished:** 2026-11-19T00:40:14Z by `cloud-demo`

## Claude Code report

## Summary
I read `hub/redact.py`: nine regexes, applied in order, with no tests. As the task required, I asked Codex for a read-only review focused on missed secret patterns. Codex came back with "no blocking issues found. VERDICT: APPROVE" and no detail. That review probably checked nothing: the tool reviews uncommitted changes, and in plan mode there are none, so `redact.py` was likely never looked at. The three proposals below come from my own reading of the file. I didn't change any files.

**Proposals (by impact):**

1. **Catch JSON/YAML-style secrets and secrets in more URL schemes.**
   - The `key=value` pattern (line 14) expects `=` or `:` right after the key name. So a quoted key like `"password": "hunter2"` or `"api_key": "..."` is not caught, because the closing quote comes first. That is the most common shape in logs and API responses. Fix: allow an optional quote, e.g. `(?:api[_-]?key|secret|password|passwd|token)["']?\s*[=:]\s*`.
   - The URL-credentials pattern (line 15) only checks `https://`. It misses `http://`, `postgres://user:pass@`, `redis://`, `mongodb+srv://` and similar. Fix: use `[a-z][a-z0-9+.\-]*://`.

2. **Add common token formats that are currently missed.**
   - **PEM private keys:** `-----BEGIN [A-Z ]*PRIVATE KEY-----` through the matching `END` line (needs `re.S`).
   - **JWTs:** `eyJ[\w-]+\.[\w-]+\.[\w-]+`. These often appear outside an `Authorization:` header.
   - **AWS temporary keys** starting with `ASIA`. An AWS secret access key (40 characters) is only caught today when it appears next to the word "secret".
   - **Other formats:** Google API keys (`AIza[0-9A-Za-z_\-]{35}`), Stripe keys (`[sr]k_(live|test)_…`, which use `_` so the `sk-` rule doesn't match), and npm tokens (`npm_…`).

3. **Add a regression test file, `tests/test_redact.py`.** It should cover positive samples for every pattern (including the ones above) and negative samples so ordinary text isn't over-redacted. One existing case to watch is the `sk-` rule, which would also redact hyphenated words such as `[REDACTED]`. Tests would let pattern changes be reviewed safely and would give the Codex review a real diff to look at.

## Changes
None.

## Codex delegation
- `codex_review`: read-only review of `hub/redact.py`, focused on missed secret patterns. It returned APPROVE with no findings. Because there were no uncommitted changes, it probably didn't review the file, so I'm not counting it as a real check.

## Verification
Not verified. This was a plan task, so I didn't run any code or tests. The findings come from reading the code.

## Needs owner action
- Decide which proposals to implement, then send them as an `implement` task.
- To get a real Codex review of a file that has no uncommitted changes, the review tool needs to be able to target specific files, or the review should happen after an implement step.

_This branch is not merged anywhere. Review it and open a PR manually if acceptable._
