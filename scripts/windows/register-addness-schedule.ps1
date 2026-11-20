# AI Agent Hub - OPTIONAL: run one Addness intake cycle every N minutes via Task Scheduler.
# This enables UNATTENDED execution of Addness tasks. Run it ONLY after the owner approved auto-run
# and after an isolated test passed (docs/ADDNESS-INTAKE.md).
# - Runs as the current user (not admin), only while logged on, so it uses your own Claude/Codex/Addness logins.
# - StartWhenAvailable: a run missed during sleep/shutdown starts after wake/boot.
# - MultipleInstances IgnoreNew + the runner's lock file: never two cycles at once.
# Remove later:  Unregister-ScheduledTask -TaskName "AIAgentHubAddnessIntake" -Confirm:$false
param([switch]$IUnderstandThisEnablesAutoRun, [int]$EveryMinutes = 5)
if (-not $IUnderstandThisEnablesAutoRun) {
  Write-Host "Refusing: pass -IUnderstandThisEnablesAutoRun after owner approval."; exit 1
}
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$repo\scripts\windows\start-addness-cycle.ps1`"" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "AIAgentHubAddnessIntake" -Action $action -Trigger $trigger -Settings $settings `
  -Description "AI Agent Hub: Addness -> Claude Code -> Codex -> Addness (one cycle per run)" -RunLevel Limited
Write-Host "Registered: every $EveryMinutes min as $env:USERNAME. Logs: state\logs\addness.log"
