<#
.SYNOPSIS
Pull latest from remote and re-apply (Windows).
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

# Prefer pwsh (PS7) for the installer — avoids a PS 5.1 quirk where
# Get-FileHash is missing under non-interactive SSH sessions.
$installer = "$repo\scripts\install-windows.ps1"
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue

Push-Location $repo
try {
    $gitRootOutput = @(git rev-parse --show-toplevel)
    $gitRootCode = $LASTEXITCODE
    if ($gitRootCode -ne 0 -or $gitRootOutput.Count -ne 1) {
        Write-Host "Unable to identify the Git root (exit $gitRootCode) -- aborting before sync." -ForegroundColor Red
        exit 1
    }
    $sourceRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $repo).ProviderPath).TrimEnd([char[]]'\/')
    $gitRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath ([string]$gitRootOutput[0])).ProviderPath).TrimEnd([char[]]'\/')
    if (-not [string]::Equals($gitRoot, $sourceRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "Git root does not match sync source -- aborting before status/pull/install." -ForegroundColor Red
        Write-Host "Git root: $gitRoot" -ForegroundColor Red
        Write-Host "Sync source: $sourceRoot" -ForegroundColor Red
        exit 1
    }

    $dirty = git status --porcelain --untracked-files=all
    if ($LASTEXITCODE -ne 0) {
        Write-Host "git status failed (exit $LASTEXITCODE) -- aborting before sync." -ForegroundColor Red
        exit 1
    }
    if ($dirty) {
        Write-Host "Working tree is dirty -- aborting sync before pull/install." -ForegroundColor Red
        Write-Host "Commit/stash changes first, or run the installer directly if you intentionally want a dirty working-tree install." -ForegroundColor Yellow
        exit 1
    }

    Write-Host "=== git pull ===" -ForegroundColor Cyan
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        # Native commands don't throw under $ErrorActionPreference='Stop' --
        # without this check a failed/offline pull would install the stale
        # checkout and report success (mirrors sync.sh's set -e).
        Write-Host "git pull failed (exit $LASTEXITCODE) -- aborting before install." -ForegroundColor Red
        exit 1
    }
    Write-Host "`n=== install ===" -ForegroundColor Cyan
    if ($pwsh) {
        & $pwsh.Source -NoProfile -ExecutionPolicy Bypass -File $installer @args
    } else {
        & $installer @args
    }
    # Same hazard class as the pull check above: without this, a failed install
    # reports success to an unattended `ssh pc ... sync.ps1` propagation
    # (sync.sh side is covered by set -e).
    $code = $LASTEXITCODE
    if ($null -ne $code -and $code -ne 0) {
        Write-Host "install failed (exit $code) -- sync did NOT complete." -ForegroundColor Red
        exit $code
    }
} finally {
    Pop-Location
}
