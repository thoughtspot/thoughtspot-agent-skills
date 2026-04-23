# Install ThoughtSpot Cursor rules into a project directory.
#
# Usage (PowerShell):
#   # Install into the current directory
#   & "$env:USERPROFILE\Dev\thoughtspot-agent-skills\agents\cursor\scripts\install.ps1"
#
#   # Install into a specific directory
#   & "$env:USERPROFILE\Dev\thoughtspot-agent-skills\agents\cursor\scripts\install.ps1" -Target "C:\path\to\project"
#
# What it does:
#   1. Creates .cursor\rules\ in the target project (if it doesn't exist)
#   2. Creates symbolic links for each .mdc file from this repo into .cursor\rules\
#   3. Creates $env:USERPROFILE\.cursor\shared symlink → agents\shared\ (once, global)
#
# Note: Creating symbolic links on Windows requires either:
#   - Running PowerShell as Administrator, OR
#   - Developer Mode enabled (Settings → Update & Security → For Developers → Developer Mode)
#
# To update rules after a git pull: no action needed — symlinks pick up changes automatically.

param(
    [string]$Target = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoDir  = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
$RulesSrc = Join-Path $RepoDir "agents\cursor\rules"
$Target   = (Resolve-Path $Target).Path

Write-Host "Installing ThoughtSpot Cursor rules into: $Target"

# ── 1. Create .cursor\rules\ ──────────────────────────────────────────────────
$RulesDest = Join-Path $Target ".cursor\rules"
New-Item -ItemType Directory -Force $RulesDest | Out-Null

# ── 2. Symlink each .mdc file ─────────────────────────────────────────────────
$Linked = 0
Get-ChildItem (Join-Path $RulesSrc "*.mdc") | ForEach-Object {
    $Src  = $_.FullName
    $Name = $_.Name
    $Dest = Join-Path $RulesDest $Name

    if (Test-Path $Dest) {
        $item = Get-Item $Dest -Force
        if ($item.LinkType -eq "SymbolicLink") {
            Write-Host "  skipped (already linked): $Name"
        } else {
            Write-Host "  skipped (file exists, not a symlink): $Name — remove it manually to link"
        }
    } else {
        try {
            New-Item -ItemType SymbolicLink -Path $Dest -Target $Src | Out-Null
            Write-Host "  linked: $Name"
            $Linked++
        } catch {
            Write-Host "  ERROR linking $Name`: $_"
            Write-Host "  Try running PowerShell as Administrator or enable Developer Mode."
        }
    }
}

# ── 3. Create $env:USERPROFILE\.cursor\shared symlink (global, one-time) ──────
$SharedSrc  = Join-Path $RepoDir "agents\shared"
$CursorDir  = Join-Path $env:USERPROFILE ".cursor"
$SharedDest = Join-Path $CursorDir "shared"

New-Item -ItemType Directory -Force $CursorDir | Out-Null

if (Test-Path $SharedDest) {
    $item = Get-Item $SharedDest -Force
    if ($item.LinkType -eq "SymbolicLink") {
        Write-Host "  ~/.cursor/shared already linked"
    } else {
        Write-Host "  WARNING: $SharedDest exists and is not a symlink — skipping"
        Write-Host "           Remove it manually and re-run if you want the symlink created."
    }
} else {
    try {
        New-Item -ItemType SymbolicLink -Path $SharedDest -Target $SharedSrc | Out-Null
        Write-Host "  linked: $SharedDest -> $SharedSrc"
    } catch {
        Write-Host "  ERROR creating shared symlink: $_"
        Write-Host "  Try running PowerShell as Administrator or enable Developer Mode."
    }
}

Write-Host ""
Write-Host "Done. $Linked rule(s) installed."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. pip install requests pyyaml keyring snowflake-connector-python cryptography"
Write-Host "  2. pip install -e $RepoDir\tools\ts-cli"
Write-Host "  3. Open your project in Cursor and ask: 'Set up my ThoughtSpot profile'"
