# Non-destructive Windows preflight for oh-my-claudecode.
# This script does not install, execute agent work, modify settings, or contact external services.
$ErrorActionPreference = "Continue"
Write-Host "AI Agent Hub / oh-my-claudecode preflight (read-only)"
foreach ($name in @("claude", "codex", "node", "npm", "git", "psmux", "tmux", "omc")) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) {
    Write-Host ("FOUND {0}: {1}" -f $name, $cmd.Source)
  } else {
    Write-Host ("MISSING {0}" -f $name)
  }
}
$paths = @(
  (Join-Path $HOME ".claude\settings.json"),
  (Join-Path $HOME ".claude\plugins\installed_plugins.json"),
  (Join-Path $HOME ".claude\plugins\known_marketplaces.json"),
  (Join-Path $HOME ".codex\config.toml")
)
foreach ($path in $paths) {
  if (Test-Path $path) {
    Write-Host "EXISTS config: $path"
  } else {
    Write-Host "ABSENT config: $path"
  }
}
Write-Host ""
Write-Host "NEXT (interactive Claude Code session only, after checking plugin conflicts):"
Write-Host "/plugin marketplace add https://github.com/Yeachan-Heo/oh-my-claudecode"
Write-Host "/plugin install oh-my-claudecode"
Write-Host "/omc-setup"
Write-Host "Do not paste slash commands into PowerShell."
Write-Host "Note: named autopilot workflow profiles require Linux flock in current upstream docs."
