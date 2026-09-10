# dev-setup-codex-community

A portable Codex workflow bundle: reusable skills, project templates, health checks,
saved handoffs and native hook adapters. Windows and macOS share one Python installer.
This distribution removes the original owner's accounts, machine settings and history.

Start with [START-HERE.md](START-HERE.md). It includes an English/Korean request to
give the receiving Codex, an environment check, install preview and recovery commands.

## Install

Install Python 3.11+ and Codex first. Git and Git Bash are needed for project freshness
and shell hook workflows; PyYAML is needed by the linters.

Extract the ZIP to a permanent directory. Then run from that directory:

```powershell
python scripts\onboard.py
python scripts\onboard.py --apply
```

```bash
python3 scripts/onboard.py
python3 scripts/onboard.py --apply
```

Use a virtual environment if your Python installation requires one. Keep its interpreter
available while the installed hooks refer to it. An extracted release needs no Git history
or GitHub account to install. No administrator or sudo access is required.
Onboarding creates a local `.runtime` environment when PyYAML is missing; it never uses
global pip. Existing prepared environments can use the platform installers directly.
Those also support `-Preview` on Windows and `--dry-run` on macOS.
The supported interpreter must be available as `python`, `python3`, or `py` on PATH.
For a versioned Homebrew Python, activate its virtual environment or add the formula's
`libexec/bin` directory to PATH. CODEX_HOME and its ancestors must be real directories;
linked paths are rejected by the installer. On macOS, resolve `/var` or `/tmp` aliases
to their `/private/...` paths when using temporary test locations.

The installer targets the current user's `~/.codex`, or `CODEX_HOME` when set. It:

- Adds or updates its `DEV-SETUP-CODEX` block in `AGENTS.md`, preserving other policy.
- Installs the skills listed in [SKILLS.md](SKILLS.md), backs up replacements, and
  preserves files it has not previously managed.
- Merges its native hook definitions and records a content hash baseline.

Existing files at shipped skill paths are backed up and replaced. Unrelated skills,
system skills, SSH files, `config.toml`, authentication, model choices, provider settings
and permission settings remain user-owned. This is a per-user distribution; each OS
account installs separately. Do not run two harness variants against the same CODEX_HOME
unless you intend their overlapping skill and hook definitions to be replaced.

Review changed hook definitions in Codex's hook trust UI (`/hooks` where available).
Installation and a clean setup-check establish file/configuration state. They do not
establish trust or prove the host dispatched an event. Hook API support varies by host.
Git Bash must be installed on Windows for shell-based project templates.

## Usage

Ask Codex to use `dev-setup status`, `dev-setup project-init`, `doctor`, `codebase-wiki`,
`research-kb`, or another installed skill. No default model is imposed. Select native
roles from the host's actual catalog and authorize bounded delegation once; reuse those
choices across sessions unless current instructions or platform constraints override them.
Project `.codex/agent-routing.json` takes priority over optional user-owned defaults at
`CODEX_HOME/dev-setup-codex-community/agent-routing.json`. The installer supplies neither
mapping and preserves the recipient's choices. Managed launches require fresh attestation;
invalid explicit settings never silently fall back. See
[docs/NATIVE_AGENT_CONTRACT.md](docs/NATIVE_AGENT_CONTRACT.md) for the routing contract.
Consultations remain explicit and use your own Codex login.

To enable knowledge capture in a project, preview
`python scripts/init-knowledge.py /absolute/project/path --hooks`, then add `--apply`.
Existing project files are preserved. The installed policy requires timely delta capture
and full reasoning preservation; semantic distillation remains agent-owned. Read
[docs/KNOWLEDGE-WORKFLOW.md](docs/KNOWLEDGE-WORKFLOW.md) for the complete procedure.

Scripts run from this directory; installed skills discover its location from
`CODEX_HOME/dev-setup-codex-community-state.json`. Keep the directory available.
To update a ZIP installation, extract a new release and run its installer, then
setup-check. Do not delete the source folder still referenced by your hooks.
For a Git clone, `scripts/sync.ps1` or `scripts/sync.sh` updates its existing remote.
Bootstrap requires an explicit repository URL; no personal repository is configured.
Rollback and uninstall are preview-first commands in `scripts/install.py`. They use
local recovery snapshots and refuse files modified after installation. See START-HERE.md.

## Development and release

```text
python scripts/lint.py
python -m unittest discover -s tests
python scripts/package.py
```

The last command writes a deterministic ZIP and SHA-256 file under `dist/` using an
allowlist. It excludes Git history, caches, logs, runtime state and private notes.
See [docs/PACKAGING.md](docs/PACKAGING.md) for scope and measured validation.
See [NOTICE.md](NOTICE.md) for attribution and licensing status.

Official skill format reference: https://developers.openai.com/codex/skills
