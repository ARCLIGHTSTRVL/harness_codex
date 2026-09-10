# harness_codex

`harness_codex` is a portable workflow harness for Codex on Windows and macOS. It
installs reusable skills, project templates, health checks, saved handoff support and
native hook adapters through one shared Python installer.

The harness is built around bounded autonomous units. A unit has a concrete outcome,
relevant context, acceptance checks and evidence tied to the current source. Code is the
source of truth for behavior. New prose comments and docstrings are limited to a short,
stable file-purpose statement. The code-derived `wiki/` explains mechanics, while
`knowledge/` preserves full decisions, alternatives, evidence and risks. `NEXT.md`
carries one active handoff.

Delegation is optional and model-neutral. The recipient chooses supported models and
reasoning efforts from their own host catalog. This repository ships no account data,
provider configuration, credentials or fixed model assignments.

## Install

Prerequisites:

- Codex and Python 3.11 or newer
- Git
- Git Bash on Windows for shell-based project hook templates

The canonical public source is
[public repository](https://github.com/ARCLIGHTSTRVL/harness_codex). For an
initial Git install, clone it into a new permanent directory:

```powershell
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git C:\path\to\harness_codex
```

```bash
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git /path/to/harness_codex
```

You can also choose **Download ZIP** from that public repository and extract it into a
permanent directory named `harness_codex`. Hooks refer to that directory after
installation, so do not install from a temporary attachment viewer. If the destination
already exists, inspect it and choose another destination instead of overwriting it.

From PowerShell:

```powershell
cd C:\path\to\harness_codex
python scripts\onboard.py
python scripts\onboard.py --apply
python scripts\setup-check.py
```

From macOS using Bash:

```bash
cd /path/to/harness_codex
python3 scripts/onboard.py
python3 scripts/onboard.py --apply
python3 scripts/setup-check.py
```

The first onboarding command checks prerequisites and previews the target without
changing it. `--apply` performs the installation. If PyYAML is unavailable, onboarding
creates a repository-local `.runtime` virtual environment; it does not modify global
Python packages. No administrator or sudo access is required.
Onboarding and both platform installers share runtime selection, including later sync
and bootstrap calls. Status checks use the recorded installation interpreter for hook
verification, even when launched by another Python.

On Windows, standard CPython and MSYS2 UCRT64/MINGW64 native Windows Python are
supported. Their private venv executables may live in `Scripts/python.exe` or
`bin/python.exe`; installation detects and validates the existing layout. Use
PowerShell for the Windows wrapper. MSYS `/usr/bin/python` is a POSIX runtime and
cannot be used as the interpreter for native Windows hook commands. If it appears
first on PATH, run `powershell -NoProfile -ExecutionPolicy Bypass -File
scripts/install-windows.ps1 -Preview`, then the same command without `-Preview`.
The wrapper skips POSIX candidates and looks for a native Python already on PATH.

The installer targets the current user's `~/.codex`, or `CODEX_HOME` when set. It:

- Merges its managed policy block into `AGENTS.md` and preserves other instructions.
- Installs the skills listed in [SKILLS.md](SKILLS.md), backing up replaced managed paths.
- Merges native hook definitions and records a content-hash baseline for drift checks.
- Leaves unrelated skills, system skills, SSH configuration, Codex configuration,
  authentication, providers, permissions and model choices under the user's control.

Existing files at shipped skill paths are backed up and replaced. Do not install two
harness variants into the same `CODEX_HOME` unless replacing their overlapping skills
and hooks is intentional. `CODEX_HOME` and its ancestors must be real directories;
linked paths are refused. On macOS, resolve `/var` and `/tmp` aliases to `/private/...`
when supplying temporary test paths.

Review changed hook definitions in Codex's hook UI (`/hooks` where supported), then open
a new session if needed. A clean setup check proves installed bytes and configuration.
It does not prove hook trust, host event delivery or model-visible context.

For an install request that another user can give directly to Codex, see
[START-HERE.md](START-HERE.md).

## Use the workflow

Ask Codex to use an installed skill such as `dev-setup status`, `dev-setup project-init`,
`doctor`, `codebase-wiki`, `knowledge-fragment` or `research-kb`. The policy keeps work
scoped to an accepted unit, verifies behavior against source and runnable checks, and
records durable reasoning in the appropriate project layer.

To add the knowledge workflow to an existing project, preview first and then apply:

```text
python scripts/init-knowledge.py /absolute/path/to/project --hooks
python scripts/init-knowledge.py /absolute/path/to/project --hooks --apply
```

The initializer creates only missing files. Existing project files and hook definitions
are preserved. The agent owns semantic capture and distillation; scripts validate,
apply and archive selected records. Hooks can preserve a written handoff, but cannot
reconstruct decisions that were never recorded. See
[docs/KNOWLEDGE-WORKFLOW.md](docs/KNOWLEDGE-WORKFLOW.md).

Optional native role routing reads project choices first and recipient-owned global
choices second. Installation creates neither mapping. Managed launches still require a
fresh catalog and source attestation. See
[docs/NATIVE_AGENT_CONTRACT.md](docs/NATIVE_AGENT_CONTRACT.md).

## Update

For a clean Git checkout, run the platform sync wrapper from the repository root:

```powershell
.\scripts\sync.ps1
python scripts\setup-check.py
```

```bash
bash scripts/sync.sh
python3 scripts/setup-check.py
```

Before syncing, inspect the checkout's configured remote and tracking branch:

```text
git remote -v
git branch --show-current
git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
```

Sync refuses a dirty working tree, pulls the current branch's configured tracking remote
and branch with `--ff-only`, and applies the installer. It does not run setup-check.
The source directory must itself be the Git root; extracting a ZIP inside another
checkout does not make that ZIP updatable. After rollback, sync uses the state's
`update_repo` checkout while status checks use its restored `source_repo`.
If the checkout tracks a fork or another custom source, report that source and leave its
remote unchanged; sync uses the configured tracking source. Run the shown setup check
afterward to verify the local installed state. The normal check is offline and prints the
canonical public repository while stating that its latest revision was not checked. To
request a public comparison, run this separately from the repository root:

```powershell
python scripts\setup-check.py --check-updates
```

```bash
python3 scripts/setup-check.py --check-updates
```

That opt-in comparison asks the canonical `main` ref for its current tip and compares it
with the checkout's root `HEAD`. It reports equal, different or unknown; it does not claim
that either commit is an ancestor of the other.

To move a ZIP installation to the public Git source, keep the extracted directory intact
and clone into a new destination, then install from the clone:

```powershell
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git C:\path\to\harness_codex-git
Set-Location C:\path\to\harness_codex-git
python scripts\onboard.py
python scripts\onboard.py --apply
python scripts\setup-check.py
```

```bash
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git /path/to/harness_codex-git
cd /path/to/harness_codex-git
python3 scripts/onboard.py
python3 scripts/onboard.py --apply
python3 scripts/setup-check.py
```

Do not re-initialize the ZIP directory as Git, overwrite an existing destination, or
retarget a fork/custom remote automatically. A ZIP has no Git history, so its local
setup-check remains available while its public update comparison is unknown.

The repository display name is `harness_codex`. Versioned ZIP names, installed state
files and internal community namespaces retain their existing names so upgrades can
recognize earlier installations.

## Roll back or uninstall

Recovery is preview-first. Supply the user's home directory, this repository directory
and the current platform:

```text
python scripts/install.py rollback --home USER_HOME --repo THIS_FOLDER --platform windows
```

Use `mac` on macOS and add `--apply` only after reviewing the plan. Replace `rollback`
with `uninstall` to restore the baseline before all recorded installs. Recovery refuses
targets changed after installation. Edits made between upgrades can require rolling back
one version at a time. There is no force-overwrite recovery mode.

Rollback activates the prior preserved source for hook execution without resetting the
working checkout. Keep the recorded Python runtime available; its binaries are not
included in source recovery. The sync skill uses the retained update checkout afterward.

Recovery snapshots remain local under `CODEX_HOME` and may contain original file bytes;
do not publish them. See [START-HERE.md](START-HERE.md) for the full recovery boundary.

## Develop and package

```text
python scripts/lint.py
python -m unittest discover -s tests
python scripts/package.py
```

Packaging writes a deterministic ZIP and SHA-256 sidecar under `dist/`. The allowlist
excludes Git history, the repository-only pre-commit hook, caches, logs, runtime state,
account data and private notes. See [docs/PACKAGING.md](docs/PACKAGING.md) for the measured
validation record and [NOTICE.md](NOTICE.md) for attribution and current license status.

Official skill format reference: https://developers.openai.com/codex/skills
