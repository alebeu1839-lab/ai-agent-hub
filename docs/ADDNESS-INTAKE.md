# Addness 受信 → Claude Code → Codex → Addness 書き戻し

GPTが本家Addnessに `【Claude Code PC】` タスクを登録すると、PCのランナーがボタン操作なしで受信し、
既存のキュー・ランナー（Claude Code → Codex）で処理して、同じAddnessタスクへ結果を書き戻す仕組み。

```
GPT（スマホ）── Addnessに【Claude Code PC】タスク登録
                     │  （PCのTask Schedulerが数分ごとに1サイクル起動）
                     ▼
hub/addness_intake.py  ① 受信: 検索 → 選別 → claimコメント → 再読込で先着確認 → agent-queueに投入
hub/runner.py          ② 実行: Claude Code（--restricted）→ Codex（MCPブリッジ）→ レビュー → agent/<id> にpush
hub/addness_intake.py  ③ 書戻し: 結果・レビュー判定・テスト・コミットSHA・未解決事項をタスク詳細へ追記＋doneコメント
```

Addnessへのアクセスは `claude -p` から **PCのClaude Codeに既に登録済みのAddness MCP接続**を使う
（`hub/addness.py` の `ClaudeMcpAddnessClient`）。Addnessのトークンはリポジトリにも設定にも置かない。
使うMCPツールは操作ごとに1つだけ許可（`search_goals` / `get_goal` / `add_comment` / `write_goal_detail` / `complete_goal`）。
削除・移動・担当変更はしない。`complete_on_pass` が `true` の場合、キュー状態が `done` でClaude Codeレビューが `PASS` のタスクだけ、結果の詳細を書き戻した後に自動完了する。既定値は `false`（設定例は `true`）。

## 受信ルール（`config/hub.config.json` の `addness`）

| 条件 | 設定 | 既定 |
|---|---|---|
| タイトルが接頭辞で始まる | `title_prefix` | `【Claude Code PC】` |
| 未完了 | — | 完了済みは除外 |
| 指定した親ゴールの配下 | `allowed_parent_titles` | 例: AI社員運用基盤を作る… |
| 除外ゴール | `excluded_goal_ids` | `21c5ea2e…`（My Addness配下） |
| 階層に語を含むものは除外 | `excluded_path_keywords` | `My Addness` |
| 本人の実行指示がある（任意） | `require_go_marker` | なし（例: `実行指示`） |
| タスクの担当者が本人（任意・推奨） | `allowed_owner_names` | なし（本人の表示名を入れる） |
| 本人の停止 | コメントに `[ai-agent-hub:stop]` だけの行 | — |
| 1サイクルで受信する件数 | `max_tasks_per_cycle` | 1 |

作業先は `target_repo` / `base_branch`（検証中は検証ブランチ）。作業結果は必ず `agent/addness-<goal_id>` に出て、mainには入らない。

## 重複防止・排他・障害時

| 仕組み | 内容 |
|---|---|
| ローカル台帳 | `state/addness/ledger.json`（原子的に書換え）。処理済み・取得済みは再取得しない |
| Addness上の印 | `[ai-agent-hub:claim …]` / `[ai-agent-hub:done …]` コメント。別PC・台帳消失時も重複しない |
| 先着確認 | claim後に再読込し、最初のclaimが自分でなければ手を引く（2台同時でも1台だけが処理） |
| キュー | 同じタスクIDが既にあれば投入しない |
| 多重起動 | `state/addness/cycle.lock`。2時間以上古いロックは異常終了とみなし解除 |
| 停止 | `state/PAUSE` またはキューの `queue/PAUSE`。削除で再開 |
| 再起動・スリープ | claim直後に落ちても次回自分のclaimを見つけて1回だけ投入。実行中の中断は既存ランナーが `--resume` で再開。スケジューラは `StartWhenAvailable` で復帰後に実行 |
| Addness認証切れ | 処理を止め `state/addness/status.json` とキューの `queue/addness_intake_status.md` に「blocked: addness auth」と本人の操作手順を記録（Addnessに書けない時もGPTが見える）。再ログイン後は自動で再開 |
| 書戻し失敗 | 台帳に残り、次のサイクルで再試行（詳細追記は1回だけ） |
| 実行失敗 | Addnessに「確認待ち」として状態・エラー・未解決事項を書き戻す |

## レビューと差し戻し

`prompts/claude-orchestrator.md` で、Claude Codeは各 `codex_implement` 後に差分とテストを確認し、
不合格なら指摘を付けて `codex_implement` へ差し戻す（最大3往復）。報告の `## Review verdict` に
PASS/FAILと各ラウンドの経緯を書き、書戻しにそのまま使う。

## PCへの導入（本人の操作）

1. 既存手順 `docs/SETUP-CLAUDE-CODE.md` でランナーを導入済みにする（Claude/Codexはサブスクリプションでログイン）。
2. PCのClaude CodeにAddness MCPが登録・認証済みか確認: `claude mcp list` に addness が出ること。
   サーバー名が違う場合は `addness.mcp_server_name` を合わせる。
3. `config\hub.config.json` に `config\hub.config.example.json` の `addness` 節を写し、まず `"enabled": true` で手動1回:
   `.\scripts\windows\start-addness-cycle.ps1`
4. 練習タスクで往復を確認したら、本人承認のうえ自動化:
   `.\scripts\windows\register-addness-schedule.ps1 -IUnderstandThisEnablesAutoRun`（5分ごと、本人ユーザー権限）

### 既存の `dispatch.ps1` とつなぐ場合

`C:\Users\saisa\Documents\AI作業場\automations\Claude Code PC受信\dispatch.ps1` が既に定期起動されているなら、
二重の受信を避けるため、**どちらか一方だけ**を受信担当にする。dispatch.ps1を残す場合は、その中の
Addness取得処理の代わりに次の1行を呼ぶ:

```powershell
& "<ai-agent-hubのフォルダ>\scripts\windows\start-addness-cycle.ps1"
```

（このクラウド作業からはdispatch.ps1の中身を読めていない。PC側で突き合わせが必要。）

## 練習の再利用手順

1. 隔離E2E（アカウント不要・何も外部に書かない）: `python scripts/e2e_isolated.py --out evidence.md`
   → 認証切れ→復旧→受信→Codex実装→レビュー差し戻し→再実装→合格→書戻し→再起動・2台目で重複なし、を一通り再現。
2. テスト一式: `python -m unittest discover -s tests -t .`
3. 実機の練習: Addnessに `【Claude Code PC】` 練習タスク（READMEの1行修正など）を親ゴール配下に作り、
   `start-addness-cycle.ps1` を1回実行。タスク詳細に結果とSHAが追記され、`agent/addness-<id>` ブランチができれば成功。
   もう一度実行して何も起きない（重複しない）ことも確認する。
