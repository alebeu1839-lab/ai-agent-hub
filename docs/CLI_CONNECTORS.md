# Codex / Claude Code adapter preparation

The new `CLIAdapter` provides a **local-only opt-in bridge**. It is disabled by default.

**Not connected yet.** Neither this GitHub repository nor the current ChatGPT
conversation can assume access to a locally installed Codex CLI or Claude Code.

Before enabling:
1. On an authorized developer computer, check installed CLI versions and exact
   noninteractive command syntax in the vendor's current documentation.
2. Verify permitted access/terms and local credentials; do not commit tokens.
3. Configure `CLIConfig` with the verified binary, fixed arguments, a restricted
   working directory, a bounded timeout and explicit `enabled=True`.
4. Run on mock internal tasks first. Replace `unpersisted://` with authenticated
   artifact storage and verification before accepting outputs.
5. Supply secure credentials via an approved secret manager, not a task payload.
6. Disable external submissions, email, paid actions and uncontrolled git pushes.

There is **no live GPT API connector** here, and no API billing was enabled.
ChatGPT subscription access does not itself grant a reusable API key.
