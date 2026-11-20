# AI Agent Hub - start the runner in the foreground (Ctrl+C to stop).
# Usage:  .\scripts\windows\start-runner.ps1            # poll loop
#         .\scripts\windows\start-runner.ps1 -Once      # process at most one task, then exit
param([switch]$Once)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
if (-not (Test-Path "config\hub.config.json")) { throw "config\hub.config.json missing (copy from hub.config.example.json)" }
$env:PYTHONUTF8 = "1"
$cmd = if ($Once) { "once" } else { "loop" }
python -m hub.runner --config config\hub.config.json $cmd
exit $LASTEXITCODE
