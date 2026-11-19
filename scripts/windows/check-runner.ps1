# AI Agent Hub - prerequisite check for the Windows runner (read-only, changes nothing).
# Usage (PowerShell, in the repo folder):  .\scripts\windows\check-runner.ps1
$ErrorActionPreference = "Continue"
$ok = $true
function Check($name, $cmd) {
  $c = Get-Command $cmd -ErrorAction SilentlyContinue
  if ($c) { Write-Host "[OK]   $name -> $($c.Source)" } else { Write-Host "[MISS] $name ($cmd not found)"; $script:ok = $false }
}
Check "Git" "git"
Check "Python 3.10+" "python"
Check "Claude Code CLI" "claude"
Check "Codex CLI" "codex"
Check "GitHub CLI (submitter verification)" "gh"

if (Get-Command python -ErrorAction SilentlyContinue) { python --version }
if (Get-Command claude -ErrorAction SilentlyContinue) { claude --version }
if (Get-Command codex -ErrorAction SilentlyContinue) {
  codex --version
  codex login status
  if ($LASTEXITCODE -ne 0) { Write-Host "[TODO] run: codex login   (sign in with your own account)"; $ok = $false }
}
if (Get-Command gh -ErrorAction SilentlyContinue) {
  gh auth status 2>&1 | Select-Object -First 3
  if ($LASTEXITCODE -ne 0) { Write-Host "[TODO] run: gh auth login"; $ok = $false }
}
if (-not (Test-Path "config\hub.config.json")) {
  Write-Host "[TODO] copy config\hub.config.example.json to config\hub.config.json and review it"
  $ok = $false
}
if ($ok) { Write-Host "`nAll prerequisites look OK." } else { Write-Host "`nFix the items above, then re-run." }
