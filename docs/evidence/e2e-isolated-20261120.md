# Isolated E2E: Addness -> Claude Code -> Codex -> review -> Addness
- sandbox: temporary directory (deleted afterwards)

## 1. Addness auth expired (owner must re-login)
- cycle -> {'status': 'blocked: addness auth'}
- queue/addness_intake_status.md:
```
# Addness intake status

- **status:** blocked: addness auth
- **runner:** `test-runner`
- **updated:** 2026-11-20T10:01:50Z
- **detail:** Addness MCP: 401 unauthorized (token expired)

**Owner action needed:** re-authenticate the Addness MCP connection in Claude Code on the runner PC (`claude` → `/mcp` → addness → authenticate). The runner keeps polling and resumes automatically.
```

## 2. Login restored: one cycle picks up the task without any button press
- cycle -> {"status": "ok", "intake": ["fe511787-f4a2-460e-a100-3e0e4a775577"], "run": "done", "writeback": ["fe511787-f4a2-460e-a100-3e0e4a775577"]}
- Codex calls (Claude -> Codex -> Claude): codex_implement:ok, codex_review:ok, codex_implement:ok, codex_review:ok
- review gate:
```
## Review verdict
PASS
round 1: changes requested -> re-delegated
round 2: approved
```
- work branch agent/addness-fe511787-f4a2-460e-a100-3e0e4a775577 @ fe77a09ce03e7aa1fe596506bf8c872abf5ff2d1
- files on work branch: CODEX_WAS_HERE.md README.md 
- files on main (unchanged): README.md 

## 3. Written back to the same Addness task
```
### 2026-11-20T10:01:52Z AI Agent Hub 実行結果（完了報告）
- キュー状態: `done`（試行 1回、0.4秒、ランナー `test-runner`）
- レビュー判定（Claude Code）: **PASS**
- Codex呼び出し: 4回 — codex_implement:ok, codex_review:ok, codex_implement:ok, codex_review:ok
- 作業ブランチ: `agent/addness-fe511787-f4a2-460e-a100-3e0e4a775577`（push: 済）／コミットSHA: `fe77a09ce03e7aa1fe596506bf8c872abf5ff2d1`

**テスト・検証**

> fake: read CODEX_WAS_HERE.md back

**未解決事項／本人の操作が必要なこと**

> なし

_詳細レポート: キューブランチ `agent-queue` の `queue/results/addness-fe511787-f4a2-460e-a100-3e0e4a775577/report.md`。マージ・デプロイはしていません。タスクの完了は担当者が判断してください。_
```
- comments:
  - 【本人から実行指示】開始してよい
  - [ai-agent-hub:claim task=addness-fe511787-f4a2-460e-a100-3e0e4a775577 runner=test-runner nonce=9e6f660ca394]
  - [ai-agent-hub:done task=addness-fe511787-f4a2-460e-a100-3e0e4a775577 status=done verdict=PASS sha=fe77a09ce03e7aa1fe596506bf8c872abf5ff2d1]
- other tasks' comments (must be no ai-agent-hub markers): {"21c5ea2e-0714-4455-bb61-b9c23cf11a90": [], "11111111-1111-4111-8111-111111111111": [], "22222222-2222-4222-8222-222222222222": [], "33333333-3333-4333-8333-333333333333": ["[ai-agent-hub:stop]"]}

## 4. Reboot / repeated runs: no duplicate pickup
- fresh process cycle -> {'status': 'ok', 'intake': [], 'run': 'idle', 'writeback': []}
- a second PC with an empty ledger -> {'status': 'ok', 'intake': [], 'run': 'idle', 'writeback': []}
- claim markers: 1, done markers: 1

**RESULT: PASS**
