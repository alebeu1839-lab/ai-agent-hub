# Agent queue

This branch is the task queue for the AI Agent Hub runner. It contains data only.

- New task: add `queue/inbox/<id>.json` (see docs/GPT-INSTRUCTIONS.md on the code branch).
- Results: `queue/results/<id>/report.md` and `result.json`.
- Overview: `queue/status.md`.
- Emergency stop: create `queue/PAUSE`. Delete it to resume.
