# AI Agent Hub - one-shot setup for the Windows runner PC.
# Paste into PowerShell (normal user, not admin):
#   irm https://raw.githubusercontent.com/alebeu1839-lab/ai-agent-hub/feat/claude-code-dispatch/scripts/windows/bootstrap.ps1 | iex
#
# What it does (safe to re-run):
#   1. installs missing tools (Git, Python, Node.js, GitHub CLI via winget; Claude Code + Codex via npm)
#   2. checks logins (subscription accounts only); opens the login flow if needed
#   3. clones/updates the repo on branch feat/claude-code-dispatch
#   4. creates config\hub.config.json from the example (no secrets in it)
#   5. runs the prerequisite check and processes ONE queued task (uses subscription quota, no API keys)
# It never stores credentials and never enables autostart.

# Continue (not Stop): PowerShell 5.1 turns native stderr into terminating errors under Stop.
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$Repo   = "https://github.com/alebeu1839-lab/ai-agent-hub.git"
$Branch = "feat/claude-code-dispatch"
$Dir    = Join-Path $env:USERPROFILE "ai-development-hub"

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

Step "1/5 Tools"
$winget = @{ git = "Git.Git"; python = "Python.Python.3.12"; node = "OpenJS.NodeJS.LTS"; gh = "GitHub.cli" }
foreach ($cmd in $winget.Keys) {
  if (Has $cmd) { Write-Host "[OK] $cmd" ; continue }
  if (-not (Has "winget")) { throw "winget not found. Install '$($winget[$cmd])' manually, then re-run." }
  Write-Host "Installing $($winget[$cmd]) ..."
  winget install --id $winget[$cmd] -e --silent --accept-package-agreements --accept-source-agreements
  Refresh-Path
}
# Windows ships a 'python' alias that opens the Store; make sure the real one works.
python --version
if ($LASTEXITCODE -ne 0) { throw "python is not working (disable the Store alias in Settings > Apps > App execution aliases)" }
foreach ($pkg in @(@("claude", "@anthropic-ai/claude-code"), @("codex", "@openai/codex"))) {
  if (Has $pkg[0]) { Write-Host "[OK] $($pkg[0])"; continue }
  Write-Host "Installing $($pkg[1]) ..."
  npm install -g $pkg[1]
  Refresh-Path
}

Step "2/5 Logins (subscription accounts only - never API keys)"
foreach ($v in "ANTHROPIC_API_KEY", "OPENAI_API_KEY") {
  if ([Environment]::GetEnvironmentVariable($v)) { Write-Host "[WARN] $v is set. The runner ignores it, but consider removing it." -ForegroundColor Yellow }
}
$auth = $null
try { $auth = claude auth status --json | ConvertFrom-Json } catch {}
if (-not $auth -or -not $auth.loggedIn) {
  Write-Host "Claude Code is not logged in. Run 'claude', choose your Claude subscription login, then /exit and re-run this script." -ForegroundColor Yellow
  return
}
Write-Host "[OK] Claude: $($auth.authMethod) / $($auth.apiProvider)"
codex login status
if ($LASTEXITCODE -ne 0) {
  Write-Host "Opening Codex login - choose 'Sign in with ChatGPT' (not API key)..." -ForegroundColor Yellow
  codex login
}
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Opening GitHub login..." -ForegroundColor Yellow
  gh auth login --hostname github.com --git-protocol https --web
}
gh auth setup-git   # git push uses your gh login (no token stored in the repo)

Step "3/5 Repository"
if (Test-Path (Join-Path $Dir ".git")) {
  git -C $Dir fetch origin $Branch
  git -C $Dir checkout $Branch
  git -C $Dir pull --ff-only origin $Branch
} else {
  git clone --branch $Branch $Repo $Dir
}
if (-not (Test-Path (Join-Path $Dir ".git"))) { throw "clone failed" }
Set-Location $Dir

Step "4/5 Config"
if (-not (Test-Path "config\hub.config.json")) {
  Copy-Item "config\hub.config.example.json" "config\hub.config.json"
  Write-Host "Created config\hub.config.json (allowlist: this repo only; subscription-only billing)."
} else { Write-Host "[OK] config\hub.config.json exists (kept)" }

Step "5/5 Check + run one task"
.\scripts\windows\check-runner.ps1
python -m unittest discover -s tests -t . 2>&1 | Select-Object -Last 3
.\scripts\windows\start-runner.ps1 -Once
Write-Host "`nDone. Result: https://github.com/alebeu1839-lab/ai-agent-hub/tree/agent-queue/queue/results" -ForegroundColor Green
Write-Host "To keep it running: .\scripts\windows\start-runner.ps1   (Ctrl+C to stop)"
