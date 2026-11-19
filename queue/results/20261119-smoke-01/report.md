# Task 20261119-smoke-01: Smoke test: redact regression tests

- **Status:** done  (attempt 1, 63.8s)
- **Mode:** implement — repo `alebeu1839-lab/ai-development-hub`, base `feat/claude-code-dispatch`
- **Work branch:** `agent/20261119-smoke-01` — pushed, compare: https://github.com/alebeu1839-lab/ai-development-hub/compare/feat/claude-code-dispatch...agent/20261119-smoke-01
- **Codex calls:** 1 — codex_implement:auth
- **Finished:** 2026-11-19T05:30:43Z by `cloud-smoke`

## Warnings
- 1 Codex call(s) failed: auth
- no successful Codex call: work was done by Claude alone or not at all

## Claude Code report

## Summary
I added `tests/test_redact.py` and it passes. Codex couldn't be used: the first call, `codex_implement`, failed with `CODEX_ERROR_KIND: auth` ("Not logged in"). Following the runner rules, I didn't retry and wrote the tests myself. I skipped `codex_test` and `codex_review` because the same login error would block them.

The file tests every pattern in `hub/redact.py`. For 12 of them the secret must become exactly `[REDACTED]`. For the `Authorization:` header and the `api_key=` / `password:` patterns, the prefix must stay and only the value is replaced. For the URL pattern, `[REDACTED]` must be replaced. Other checks:
- ordinary text, empty string and `None` must come back unchanged
- several secrets in one string are all removed
- the number of patterns must stay 14, so adding a pattern forces a new test

I found no real bug, so `hub/redact.py` is unchanged. There is one small formatting quirk: for a quoted value such as `"token": [REDACTED]"`, the opening quote is removed along with the secret, giving `"token": [REDACTED]"`. Nothing leaks. The test now expects that output, with a comment explaining why.

## Changes
- `tests/test_redact.py` (new)

## Codex delegation
- `codex_implement` (write the tests): failed with `CODEX_ERROR_KIND: auth` because Codex isn't logged in on the runner. I wrote the tests myself instead.
- `codex_test`: not called, same login error.
- `codex_review`: not called, same login error. **No independent review was done.**

## Verification
- `python3 -m unittest tests.test_redact`: 8 tests, OK.
- Full suite (`python3 -m unittest discover -s tests -t .`): 25 tests, OK.

## Needs owner action
- Run `codex login` on the runner machine. The Codex test and review steps for this task were never done, so you may want to rerun it afterwards.
- Optional: decide whether to fix the quote quirk in the `key = value` pattern by moving the optional opening quote into the capture group. It's cosmetic, so I left it.

## Diffstat
```
tests/test_redact.py | 132 +++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 132 insertions(+)
```

_This branch is not merged anywhere. Review it and open a PR manually if acceptable._
