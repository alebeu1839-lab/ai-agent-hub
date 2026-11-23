# Install oh-my-claudecode on the local Windows machine.
# Explicit operator invocation required. Never run on a production server.
# This script installs only the upstream CLI package and DOES NOT rewrite Claude/Codex settings.
param([switch]$Install)
$ErrorActionPreference = "Stop"
function Need($name) {
  $c = Get-Command $name -ErrorAction SilentlyContinue
  if (-not $c) { throw "Missing prerequisite: $name. No installation performed." }
  return $c
}
Write-Host "oh-my-claudecode Windows CLI installer (safe mode)"
$null = Need "node"; $null = Need "npm"; $null = Need "claude"; $null = Need "codex"
$v = & node --version
$major = [int](($v -replace '^v','').Split('.')[0])
if ($major -lt 22) { throw "Node.js 22+ required by this install policy; detected $v. No installation performed." }
$existing = Get-Command omc -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "OMC already installed at $($existing.Source). No modification performed."
  exit 0
}
$settings = Join-Path $HOME ".claude\settings.json"
$plugins = Join-Path $HOME ".claude\plugins"
$codex = Join-Path $HOME ".codex\config.toml"
$backupRoot = Join-Path $HOME ("omc-install-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
if (-not $Install) {
  Write-Host "Preflight OK: $v; no installation performed."
  Write-Host "Run this same script with -Install on your own Windows PC to install."
  exit 0
}
New-Item -ItemType Directory -Path $backupRoot -ErrorAction Stop | Out-Null
foreach ($p in @($settings, $codex)) {
  if (Test-Path $p) {
    $target = Join-Path $backupRoot (($p -replace '[:\\/]', '_').TrimStart('_'))
    Copy-Item -LiteralPath $p -Destination $target -ErrorAction Stop
    Write-Host "Backed up config file: $target"
  }
}
if (Test-Path $plugins) {
  # Plugin configs may contain tokens. Keep backup local, do not upload.
  $target = Join-Path $backupRoot "claude-plugins"
  Copy-Item -LiteralPath $plugins -Destination $target -Recurse -ErrorAction Stop
  Write-Host "Backed up Claude plugins in $target"
}
Write-Host "Installing official npm package; local npm permissions/auth required."
& npm install --global "oh-my-claude-sisyphus@latest"
if ($LASTEXITCODE -ne 0) { throw "npm install failed, review the log; settings backups at $backupRoot" }
$omc = Get-Command omc -ErrorAction SilentlyContinue
if (-not $omc) { throw "npm completed but omc command not found. Check PATH; backups at $backupRoot" }
Write-Host "OMC CLI present. Verify upstream setup inside a trusted Claude Code session:"
Write-Host "    /omc-setup"
Write-Host "Team mode for Codex requires a tmux-compatible local environment (psmux or WSL tmux)."
Write-Host "Do not turn on headless writes/auto-merge until the isolated integration tests pass."
Write-Host "Backup directory: $backupRoot"
