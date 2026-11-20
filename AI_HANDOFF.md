# AI Agent Hub — 共有進捗・引き継ぎ台帳

最終記録: 2026-11-20 JST
状態: **構成とGitHub保存先は確認済み／エンドツーエンド稼働は未検証**
このファイルはGPT・Claude Code・Codexが最初に読む共有入口。実行結果で裏付けられない「完成」は記載しない。

## 目的と構成
- 目的: GPTによる指示・優先順位判断 → AI Agent Hubによるキュー・実行管理 → Claude Code / Codex等による実装・検証 → 結果の回収と進捗記録。
- 本家Addnessはゴール・意思決定・作業履歴の管理先。My Addnessは別の開発プロジェクトであり、Hubの完成判定に混ぜない。
- GitHub repository: https://github.com/alebeu1839-lab/ai-agent-hub
- 旧リポジトリ名: `alebeu1839-lab/ai-development-hub`（2026-11-20に名称変更済み）

## 2026-11-20時点の確認済み事実
- GitHub上でリポジトリ名を `ai-agent-hub` に変更し、新URLで存在を再確認した。
- 確認できたブランチ名: `main`, `agent-queue`, `feat/claude-code-dispatch`, `feat/my-addness-integration-plan`, `agent/20261119-smoke-01`, `design/agent-operations-v1` 等。
- **注意**: ブランチ名が存在することは、実装済み・テスト合格・本番稼働の証明にならない。
- Claude CodeのPC上で現在どこまで進んだかは、この記録作成時に未確認。別PCのローカル作業ツリーや未pushコミットはGitHubから見えない。

## 未確認・次の検証
1. PCの作業リポジトリ、現在のbranch、HEAD SHA、未コミット差分、未pushコミットを照合。
2. リポジトリ改名による影響を点検: `git remote -v`、CI、Claude Code / Codex の設定、スクリプト、参照URL、Webhook等。旧URLの自動リダイレクトに依存せず更新対象を明示。
3. GPT → Hub のタスク登録とキュー取得をテスト。
4. Hub → Claude Code / Codex の実行、認証、失敗・再試行をテスト。
5. 実行結果・証跡（コマンド、終了コード、テスト数、コミットSHA）を回収してAddnessへ記録。
6. 1件の指示を終端まで完走して初めて「基本連携完了」と判定。24時間無人運用は別検証。

## Claude Code / Codex / GPT 共通の引き継ぎルール
- **作業開始時**: このファイルと作業ブランチの最新状態、関連PR、CI結果を確認する。実際のローカル作業状態と食い違う場合は原因を明記する。
- **作業終了時**: 下の最新状況欄を事実ベースで更新し、コミット・pushする。AIが自動でGitHubに書けない場合は、変更案を残し「未反映」とする。
- 結果は「確認済み」「未確認」「失敗」を区別。テストログ、コミットSHA、PR、実行時刻の証跡を付ける。
- 追加課金・契約・外部公開・本番デプロイ・破壊的変更は本人承認。機密鍵、認証トークン、個人情報はコミットしない。
- 同一ファイルの並列編集を避け、他AIの未コミット作業を上書きしない。
- Addnessゴール: https://www.addness.com/goals/67d0ab23-6267-4d13-aff9-359126fb62e1 （名称変更と次の検証方針を2026-11-20に記録）。

## 共通ルールの参照（2026-11-20 追加）
- 正本: Addnessナレッジ `1df7df07-8d47-4881-808f-12ea25effc8e`（Claude Codeが最後に読んだのは revision 5（10:26Z）。CLAUDE.md・AGENTS.md の控えは revision 3 のまま（無断で書き換えない））。入口は `CLAUDE.md`（Claude Code）と `AGENTS.md`（Codex。Codex CLIはリポジトリ直下のAGENTS.mdを自動で読む）。
- Codexの受領確認（PCで本人かClaude Codeが1回だけ実行、ファイル変更なし）:
  `codex exec --sandbox read-only --cd <このリポジトリ> (Get-Content prompts\codex-rules-handoff.md -Raw) | Tee-Object state\codex-rules-ack.txt`
  応答の先頭が `RULES_ACK revision=5` で、8項目が正本（rev 5）と一致すれば合格。

## 最新状況（作業したAIが更新する）
- **更新者**: Claude Code（クラウドセッション）
- **最終確認**: 2026-11-20 JST
- **作業ブランチ**: `claude/funny-johnson-d34brp`（`feat/claude-code-dispatch` をマージしたうえで追加。main は未変更）
- **何をした**: Addness受信ブリッジを追加（`hub/addness.py`, `hub/addness_intake.py`）。Addnessの【Claude Code PC】タスク → claim → 既存キュー → 既存ランナー（Claude Code→Codex）→ 同じAddnessタスクへ結果・レビュー判定・SHA・未解決事項を書戻し。レビュー差し戻しループをプロンプトに明記。Windows起動スクリプト（`start-addness-cycle.ps1`, 承認制の `register-addness-schedule.ps1`）。手順書 `docs/ADDNESS-INTAKE.md`。リポジトリ改名に合わせURLを更新。
- **テスト結果**: `python -m unittest discover -s tests -t .` 44件合格。`python scripts/e2e_isolated.py` PASS（証跡: `docs/evidence/e2e-isolated-20261120.md`）。いずれも偽のAddness・偽のclaude/codex・ローカルbare repoでの隔離検証。
- **残る問題（確認済みでないもの）**:
  1. 実PCでの実機検証が未実施（本物のAddness MCP・Claude Code・Codexでの往復）。
  2. PCの既存 `dispatch.ps1` の中身を未確認（クラウドから読めない）。二重受信を避けるため、どちらか一方を受信担当にする判断が必要。
  3. 今回の実装はCodexへ委譲できていない（このクラウド環境にCodex CLI・ChatGPTログインがない）。Claude Codeが直接実装した。
  4. 実行中タスクへの `[ai-agent-hub:stop]` は次の受信を止めるだけで、実行中の処理は止めない（止めるには PAUSE）。
  5. 他PCがclaimしたまま止まったタスクは自動で引き継がない（安全側）。手動でclaimコメントを消すか再登録。
- **次に何をする**: 本人がPCで `docs/ADDNESS-INTAKE.md` の「PCへの導入」を実施 → 練習タスク fe511787 で1回手動サイクル → 結果を確認後に自動化を承認。

### 2026-11-21 Claude Code（子ゴール引継ぎ, run-id: subgoal-handoff-20261120）
- ブランチ `claude/claude-code-pc-subgoal-handoff-b7cl6u`、HEAD `4df54fb`（Codex実装）、レビュー PASS、56件 OK。
- 実際のAddnessで `handoff.enabled=true` にして動かす確認はまだ。詳細は `docs/HANDOFF.md`。
