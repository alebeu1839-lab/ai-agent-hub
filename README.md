# AI Development Hub

ChatGPT（司令塔）→ Claude Code（開発責任者）→ Codex（実装・検証）の自動連携ランナー。

- 仕組みと安全設計: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- PCへの導入手順: [docs/SETUP-CLAUDE-CODE.md](docs/SETUP-CLAUDE-CODE.md)
- ChatGPTからの指示・結果確認: [docs/GPT-INSTRUCTIONS.md](docs/GPT-INSTRUCTIONS.md)

```
python -m unittest discover -s tests -t .                     # tests
python -m hub.runner --config config/hub.config.json once     # process one queued task
```
