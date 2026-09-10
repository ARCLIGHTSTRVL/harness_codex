---
name: setup-check
description: Read-only community source, installed policy, skill and hook verification.
---

# setup-check

Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json` (default CODEX_HOME is `~/.codex`). Use that source directory as `<repo>`. Without state, locate the extracted community directory supplied by the user; never guess a personal repository.

Run `python <repo>/scripts/setup-check.py`. Report content drift. `--home` selects a profile root; CODEX_HOME overrides the Codex directory. `--probe-hooks` executes exact command probes only. Configuration, trust and host event delivery are separate facts. ZIP installs need no Git history. SSH and credentials are not managed.
