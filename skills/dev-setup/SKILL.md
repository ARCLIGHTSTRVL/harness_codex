---
name: dev-setup
description: Community Codex harness status, sync, hooks, doctor, skills and project initialization.
---

# dev-setup

Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json` (default CODEX_HOME is `~/.codex`). Use that source directory as `<repo>`. Without state, locate the extracted community directory supplied by the user; never guess a personal repository.

Default/status: run scripts/setup-check.py. Sync: use the sync skill. Hooks: run scripts/native-hooks.py check. Doctor: run scripts/lint.py, scripts/setup-check.py and scripts/project-health.py --selftest. Project-init: use the project-init skill. Skills: read SKILLS.md. Status/hooks/skills inspection are read-only. Installation merges policy and hooks and installs skills with backups. It does not configure models, SSH, auth or permissions. Hook configuration does not prove trust or host event delivery.

Recipient-owned global role pins may live at `CODEX_HOME/dev-setup-codex-community/agent-routing.json`; a project's `.codex/agent-routing.json` takes precedence. Installation never creates or ships either mapping and preserves existing choices. With neither source, status is UNSET and the user must choose from current host discovery. Never select pins automatically. Every managed delegation requires fresh attestation.

For a received ZIP, read START-HERE.md and use scripts/onboard.py to check the environment
and preview targets, then --apply for an authorized install. Rollback/uninstall use
scripts/install.py with --home, --repo and --platform; preview is the default and --apply
performs the displayed restoration. Changed files block recovery. Never erase user edits
to make a recovery check pass. Knowledge scaffolding: scripts/init-knowledge.py PROJECT
with optional --hooks, then --apply; existing project files are preserved.
