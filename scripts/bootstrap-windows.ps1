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
    $gitRootOutput = @(git -C $Target rev-parse --show-toplevel)
    $gitRootCode = $LASTEXITCODE
    if($gitRootCode -ne 0 -or $gitRootOutput.Count -ne 1) {
        Write-Host "Unable to identify the target Git root (exit $gitRootCode) -- aborting before bootstrap update." -ForegroundColor Red
        exit 1
    }
    $targetRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Target).ProviderPath).TrimEnd([char[]]'\/')
    $gitRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath ([string]$gitRootOutput[0])).ProviderPath).TrimEnd([char[]]'\/')
    if(-not [string]::Equals($gitRoot, $targetRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "Git root does not match bootstrap target -- aborting before status/pull/install." -ForegroundColor Red
        Write-Host "Git root: $gitRoot" -ForegroundColor Red
        Write-Host "Bootstrap target: $targetRoot" -ForegroundColor Red
        exit 1
    }
    Push-Location $Target
    try {
        $dirty = git status --porcelain --untracked-files=all
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
