# ChatGPT側の使い方（司令塔）

ChatGPT は GitHub コネクタで **キューブランチ `agent-queue` にファイルを置くだけ** です。
PC 上のランナーがそれを拾い、Claude Code → Codex で作業し、結果を同じブランチに書き戻します。

## 1. 指示を出す（タスク登録）

`alebeu1839-lab/ai-agent-hub` のブランチ **`agent-queue`** に、次のファイルを作成してコミット:

`queue/inbox/<id>.json`（ファイル名と `id` は同じにする）

```json
{
  "id": "20261119-hello-01",
  "title": "挨拶ヘルパーを追加",
  "instructions": "hub_examples/hello.py に greet(name) を作り、unittest も追加。実装とテストは Codex に任せ、最後に Codex にレビューさせること。",
  "repo": "alebeu1839-lab/ai-agent-hub",
  "base_branch": "main",
  "mode": "implement",
  "requested_by": "chatgpt",
  "acceptance": ["unittest が通る", "Codex レビューが APPROVE"]
}
```

| 項目 | ルール |
|---|---|
| `id` | 英数字・`-`・`_`、3〜64文字。日付＋連番推奨 |
| `mode` | `plan`（調査・提案のみ、変更しない）または `implement`（実装） |
| `repo` | 許可リストにあるリポジトリのみ（My Addness は対象外） |
| `base_branch` | 許可パターンのみ。作業結果は必ず `agent/<id>` ブランチに出る（main には反映されない） |
| 禁止 | 認証情報・トークンを書かない。デプロイ・本番公開・課金操作は依頼しない（Claude は停止して承認を求める） |

## 2. 結果を確認する

同じ `agent-queue` ブランチで:

* `queue/status.md` … 全タスクの一覧（inbox / running / done / failed）
* `queue/results/<id>/report.md` … Claude Code の最終報告、Codex 呼び出し結果、警告、変更ブランチの比較URL
* `queue/results/<id>/result.json` … 機械可読な結果（status, error_kind, codex_calls, git 情報）

status の意味: `done` 完了 / `retry_scheduled` 一時障害で自動再試行待ち / `failed` 失敗または拒否（`REJECTED` は検証で拒否、実行されていない）。

## 3. 緊急停止・再開

* 停止: `queue/PAUSE` ファイルを作成（中身は理由でよい）。実行中のタスクは最後まで走り、次のタスクは拾われない。
* 再開: `queue/PAUSE` を削除。

## 4. ChatGPT に貼るカスタム指示（例）

```
あなたは AI Agent Hub の司令塔。開発依頼を受けたら:
1) 作業を1タスク=1目的に分解し、docs/GPT-INSTRUCTIONS.md の形式で
   alebeu1839-lab/ai-agent-hub の agent-queue ブランチ queue/inbox/<id>.json に作成する。
   まず調査が必要なら mode=plan、実装なら mode=implement。秘密情報は絶対に書かない。
2) 報告を求められたら queue/status.md と queue/results/<id>/report.md を読み、
   完了/未完了/要承認事項を要約する。warnings と error を必ず伝える。
3) main へのマージ・デプロイ・権限変更はオーナーの明示承認なしに依頼しない。
```
