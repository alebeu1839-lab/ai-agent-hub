# Codex実装依頼: 子ゴールの残件確認と「次の1件」選定（run-id: subgoal-handoff-20261120）

Claude Codeからの依頼です。正本ルール: Addnessナレッジ `1df7df07-8d47-4881-808f-12ea25effc8e` **revision 8**（2026-11-20）。
元タスク: Addness `37b415fd-1e9b-4086-b6c2-7a58217cec25`「【Claude Code PC】子ゴールの残件確認と次タスクへの継続引継ぎを整える」。

## このタスクで守るルール（rev 8 から抜粋。CodexはAddnessを直接読まない）
- Claude Codeから渡されたこのタスクだけを実装・テストし、結果をClaude Codeへ返す。Addnessへの読み書き・自主受注はしない。
- サブエージェント・並列実行はしない。1タスク1セッション。
- 強制push・main変更・マージ・デプロイ・課金・公開・メール送信はしない。秘密情報をコミットしない。
- 利用上限・認証エラー時は無限再試行せず、`docs/HANDOFF.md` に途中経過を書いて止まる。
- **無断の自動送信・自動起動を作らない**。次の子タスクは「今やるべきToDo」に*載せる*だけで、Claude Codeへの送信は本人がAddnessから行う（rev 8「子ゴールが残る場合の連続作業」）。
- 子の自動連続実行（無人継続）は実装しない。

## 作業場所
- リポジトリ `alebeu1839-lab/ai-agent-hub`、ブランチ `claude/claude-code-pc-subgoal-handoff-b7cl6u`（`claude/funny-johnson-d34brp` を取込み済み）。
- 変更してよいファイル: `hub/handoff.py`（新規）、`hub/addness.py`、`hub/addness_intake.py`、`tests/test_handoff.py`（新規）、`tests/test_addness_intake.py`、`config/hub.config.example.json`、`docs/ADDNESS-INTAKE.md`。それ以外は触らない。

## 実装内容
### 1. `hub/handoff.py`（純粋関数・I/Oなし）
`select_next(parent: dict, children: list[dict], today_ids: set[str], queue_ids: set[str], cfg: dict) -> Selection`
- `Selection` は `next: dict | None` と `skipped: list[tuple[goal_id, reason]]` と `remaining: list[dict]`（未完了の子すべて）を持つ。
- 子は表示順（入力リストの順）で評価し、最初に全条件を通った1件を `next` にする。1件も無ければ `None`（**子が無い・全部除外なら何も追加しない**）。
- 除外条件と reason（テストで1つずつ確認する）:
  | reason | 判定 |
  |---|---|
  | `completed` | status が DONE/COMPLETED/COMPLETE、または `completed_at` がある |
  | `waiting_approval` | 本文かコメントに `確認待ち` / `承認待ち` / `[ai-agent-hub:waiting]` がある、またはAIアクティビティが `waiting` |
  | `blocked_by_dependency` | 本文に `依存: <goal_id>`（複数可、全角コロン可）があり、その goal_id が兄弟の中で未完了 |
  | `needs_owner_approval` | タイトル・本文に `cfg["handoff"]["approval_keywords"]`（既定: 課金, 契約, 公開, メール送信, マージ, デプロイ, 本番）を含む |
  | `stopped` | コメントに `[ai-agent-hub:stop]` だけの行 |
  | `in_progress_elsewhere` | claim マーカーがあり done マーカーが無い、またはキューに `addness-<id>` がある、またはAIアクティビティが `working` |
  | `already_in_today` | `today_ids` に含まれる（重複追加しない。**ただしこの子が選定対象として最初に来たら `next` にはせず `already_queued_next` として結果に示す**＝既に次の1件が維持されている状態） |
  | `duplicate_title` | 先に評価した兄弟と正規化タイトル（空白・【】接頭辞除去）が同じ |
- `already_queued_next` がある時は新たに追加しない（「次の1件を維持」）。

### 2. `hub/addness.py`
- クライアントに `list_children(goal_id) -> list[dict]`、`list_today_ids() -> set[str]`、`add_today_todo(goal_id)` を追加。
  - `FakeAddnessClient`: JSONストアの `children` / `today` を使う。
  - `ClaudeMcpAddnessClient`: 1操作1ツールだけ許可（`get_goal`（sections=children）/ `list_today_todos` / `create_today_todo`）。
- 子の完了・削除・移動・担当変更はしない。

### 3. `hub/addness_intake.py`
- `writeback()` で書き戻した後、`cfg["addness"]["handoff"]["enabled"]` が真なら:
  1. 書き戻したタスクの**親**と、そのタスク自身の**直下の子**の両方を対象に `select_next` を実行（タスク自身は除く）。
  2. `next` があれば `add_today_todo` し、台帳に `handoff_added=<id>` を記録（2回目のサイクルで再追加しない）。
  3. 書戻し本文に「**残件と次の1件**」節を追加: 未完了の子の一覧（id・題・除外理由）、追加した次の1件、または「追加なし（理由）」。
- `handoff.enabled` の既定は `false`。設定例に節を追加。**ToDo追加より先にClaude Codeへ送信・起動する処理は書かない。**

### 4. テスト `tests/test_handoff.py`（＋必要なら intake の結合テスト）
最低限:
1. 未完了の子が複数 → 表示順で最初の実行可能な子が `next`。
2. 子が無い → `next is None`、`add_today_todo` が呼ばれない。
3. 依存待ち／承認待ち／完了済み／重複タイトル／他で実行中／stop がそれぞれ除外され、reason が合う。
4. 既に今日のToDoにある → 追加しない（`already_queued_next`）。
5. 結合: FakeAddnessClient で書戻し→ToDo追加1件→もう1サイクル回しても追加されない。
6. 既存テスト44件がすべて通る。

## 返却形式（Claude Codeへ）
```
CODEX_RESULT run-id=subgoal-handoff-20261120 rules=rev8
- 変更ファイル:
- 実行したテストコマンドと結果（件数・OK/FAIL）:
- コミットSHA（push済みか）:
- 仕様から外れた点・判断した点:
- 未解決:
```
