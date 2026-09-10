<#
.SYNOPSIS
Clone or update dev-setup-codex from GitHub, then install it on Windows.
#>

param(
    [Parameter(Mandatory=$true)][string]$RepoUrl,
    [string]$Target = (Join-Path $env:USERPROFILE 'dev\dev-setup-codex-community'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

if(Test-Path $Target) {
    if(-not (Test-Path (Join-Path $Target '.git'))) {
        Write-Host "Target exists but is not a git clone: $Target" -ForegroundColor Red
        exit 1
    }
    Push-Location $Target
    try {
        $dirty = git status --porcelain
        if($LASTEXITCODE -ne 0) {
            Write-Host "git status failed (exit $LASTEXITCODE) -- aborting before bootstrap update." -ForegroundColor Red
            exit 1
        }
        if($dirty) {
            Write-Host "Target clone is dirty -- aborting bootstrap update before pull/install: $Target" -ForegroundColor Red
            Write-Host "Commit/stash changes first, or run scripts\install-windows.ps1 directly if you intentionally want a dirty working-tree install." -ForegroundColor Yellow
            exit 1
        }
        git pull --ff-only
        if($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Pop-Location
    }
} else {
    $parent = Split-Path -Parent $Target
    if(-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    git clone $RepoUrl $Target
    if($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$argsForInstall = @()
if($Force) { $argsForInstall += '-Force' }
& (Join-Path $Target 'scripts\install-windows.ps1') @argsForInstall
exit $LASTEXITCODE
