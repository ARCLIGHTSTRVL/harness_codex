---
name: dev-setup
description: Community Codex harness status, sync, hooks, doctor, skills and project initialization.
---

# dev-setup

Read `source_repo` first from `CODEX_HOME/dev-setup-codex-community-state.json` (default
`CODEX_HOME` is `~/.codex`) and use that existing source directory as `<repo>`. If state
is absent or stale, inspect the supplied/current community checkout. The canonical public
source is [public repository](https://github.com/ARCLIGHTSTRVL/harness_codex); if no source
directory is available, ask the user to choose or clone one rather than silently selecting
a personal fork or arbitrary repository.

Default/status: run `python <repo>/scripts/setup-check.py`. Sync: use the sync skill from
`<repo>`. Hooks: run `python <repo>/scripts/native-hooks.py check`. Doctor: from the
`<repo>` root run `python <repo>/scripts/lint.py` and `python <repo>/scripts/setup-check.py`; run
`python <repo>/scripts/project-health.py --selftest` from the project being diagnosed.
Project-init: use the project-init skill. Skills: read `<repo>/SKILLS.md`. Status/hooks/
skills inspection are read-only. Installation merges policy and hooks and installs skills
with backups. It does not configure models, SSH, auth or permissions. Hook configuration
does not prove trust or host event delivery.

Recipient-owned global role pins may live at `CODEX_HOME/dev-setup-codex-community/agent-routing.json`; a project's `.codex/agent-routing.json` takes precedence. Installation never creates or ships either mapping and preserves existing choices. With neither source, status is UNSET and the user must choose from current host discovery. Never select pins automatically. Every managed delegation requires fresh attestation.

For a received ZIP, read `<repo>/START-HERE.md` and use `python <repo>/scripts/onboard.py`
to check the environment and preview targets, then `python <repo>/scripts/onboard.py --apply`
for an authorized install. Rollback/uninstall use `python <repo>/scripts/install.py` with
`--home`, `--repo` and `--platform`; preview is the default and `--apply` performs the
displayed restoration. Changed files block recovery. Never erase user edits to make a
recovery check pass. Knowledge scaffolding: `python <repo>/scripts/init-knowledge.py`
PROJECT with optional `--hooks`, then `--apply`; existing project files are preserved.

The normal status check is local and offline; it reports the canonical public URL and that
the latest public revision was not checked. Use the setup-check skill's explicit
`--check-updates` command for a public comparison. A Git checkout is compared by its root
`HEAD` with the canonical `main` tip and receives only equal, different or unknown; no
ancestry is inferred. ZIP status works without Git and its public comparison is unknown.
