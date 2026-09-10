---
name: sync
description: Update an existing community Git clone and apply the local installer.
---

# sync

Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json` (default CODEX_HOME is `~/.codex`). Use that source directory as `<repo>`. Without state, locate the extracted community directory supplied by the user; never guess a personal repository.

For an existing Git clone, run scripts/sync.ps1 on Windows or scripts/sync.sh on macOS. These require a clean tree and use its configured remote. For ZIP installs, use the user-selected release and rerun its installer. Never infer a repository or overwrite a dirty checkout. Verify with setup-check. No SSH configuration or automatic peer propagation is managed.
