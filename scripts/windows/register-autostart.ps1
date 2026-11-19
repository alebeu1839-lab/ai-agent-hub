# AI Agent Hub - OPTIONAL: start the runner automatically at logon via Task Scheduler.
# This enables unattended execution. Run it ONLY after the owner has approved auto-run.
# Remove later with:  Unregister-ScheduledTask -TaskName "AIAgentHubRunner" -Confirm:$false
param([switch]$IUnderstandThisEnablesAutoRun)
if (-not $IUnderstandThisEnablesAutoRun) {
  Write-Host "Refusing: pass -IUnderstandThisEnablesAutoRun after owner approval."; exit 1
}
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repo\scripts\windows\start-runner.ps1`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Days 30)
Register-ScheduledTask -TaskName "AIAgentHubRunner" -Action $action -Trigger $trigger -Settings $settings `
  -Description "AI Agent Hub runner (GPT -> Claude Code -> Codex)" -RunLevel Limited
Write-Host "Registered. It runs as $env:USERNAME (not admin) at next logon."
