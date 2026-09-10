<#
.SYNOPSIS
dev-setup-codex installer (Windows) -- bootstrap only.

.DESCRIPTION
Refreshes PATH, resolves a Python 3, and hands the whole install to
scripts/install.py, which owns every step and every rule for both platforms.
This file used to carry a second implementation of all of it in PowerShell,
and each divergence between the two decided a file's fate differently in the
two domains the install has to keep identical.

Nothing here may grow a rule. A rule added here is a rule spelled twice again,
and test_install_engine.py fails on the vocabulary of one appearing in this
file at all.

.PARAMETER Force
Re-apply even when the engine proves the install is already in sync.
#>

param([switch]$Force, [switch]$Preview)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

# Refresh $env:Path from the registry -- picks up tools installed after this shell
# started (a User PATH update from WinGet does not propagate to running processes).
# APPEND, never replace: replacing drops session-scoped entries (venv/CI/temp
# profile) and would shadow the caller's intended python with a system one.
# It must happen HERE: the engine cannot fix a PATH it was already resolved from.
$env:Path = $env:Path + ';' + [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

# ONE resolution order for the whole harness: python, python3, py. `python` first
# preserves venv/CI/temp-profile isolation; `python3` on stock Windows is a Microsoft
# Store stub that exits silently, which the version probe below rejects regardless of
# where it sits in the order. Keep this generic order identical to githooks/pre-commit,
# templates/hooks/stop-handoff-gate.sh and scripts/install-mac.sh.
# The Git gate also checks managed Homebrew paths for bare SSH environments.
$pyCmd = $null
foreach ($candidate in @('python','python3','py')) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    try {
        $versionText = (& $candidate -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null)
        if($LASTEXITCODE -eq 0 -and ($versionText | Select-Object -Last 1).Trim() -eq '1') {
            $resolvedCandidate = (& $candidate -c "import sys; print(sys.executable)" 2>$null)
            if($LASTEXITCODE -eq 0 -and $resolvedCandidate) {
                $pyCmd = [System.IO.Path]::GetFullPath(($resolvedCandidate | Select-Object -Last 1).Trim())
                break
            }
        }
    } catch { }
}
if (-not $pyCmd) {
    Write-Host "Python 3.11+ not found/runnable (tried: python, python3, py). Install Python 3.11+ and retry." -ForegroundColor Red
    exit 1
}

$engineArgs = @('install', '--home', $env:USERPROFILE, '--repo', $repo,
                '--platform', 'windows')
if($Force) { $engineArgs += '--force' }
if($Preview) { $engineArgs += '--dry-run' }
$runtimeArgs = @('--repo', $repo)
if(-not $Preview) { $runtimeArgs += '--apply' }
$runtimeArgs += '--'
$runtimeArgs += "$repo\scripts\install.py"
$runtimeArgs += $engineArgs

# try/catch is load-bearing, not decoration (reproduced on pwsh 7.6.4): under
# $PSNativeCommandUseErrorActionPreference = $true -- a supported pwsh 7 setting a
# user profile may carry -- a nonzero NATIVE exit is promoted to a terminating
# NativeCommandExitException, which under EAP=Stop aborts before $LASTEXITCODE is
# read. The engine has already printed its own reason either way; this only
# decides the code this script exits with.
try {
    & $pyCmd "$repo\scripts\runtime.py" @runtimeArgs
    $code = $LASTEXITCODE
} catch {
    $code = if($LASTEXITCODE) { $LASTEXITCODE } else { 1 }
}
exit $code
