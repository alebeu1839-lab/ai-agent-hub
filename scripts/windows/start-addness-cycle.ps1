# AI Agent Hub - Addness intake: Addness -> queue -> Claude Code -> Codex -> Addness.
# Usage:  .\scripts\windows\start-addness-cycle.ps1          # one cycle, then exit (for Task Scheduler / dispatch.ps1)
#         .\scripts\windows\start-addness-cycle.ps1 -Loop    # poll forever in the foreground (Ctrl+C to stop)
# Safe to start repeatedly: a lock file makes overlapping runs exit immediately ("locked").
# Emergency stop: create the file state\PAUSE (or queue/PAUSE on the queue branch).
param([switch]$Loop)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
if (-not (Test-Path "config\hub.config.json")) { throw "config\hub.config.json missing (copy from hub.config.example.json)" }
$env:PYTHONUTF8 = "1"
$cmd = if ($Loop) { "loop" } else { "cycle" }
python -m hub.addness_intake --config config\hub.config.json $cmd
exit $LASTEXITCODE
