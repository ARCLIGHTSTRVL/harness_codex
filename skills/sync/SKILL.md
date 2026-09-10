---
name: sync
description: Update an existing community Git clone and apply the local installer.
---

# sync

Read `source_repo` first from `CODEX_HOME/dev-setup-codex-community-state.json` (default
`CODEX_HOME` is `~/.codex`) and use that existing source directory as `<repo>`. If state
is absent or stale, inspect the supplied/current community checkout. The canonical public
source is [public repository](https://github.com/ARCLIGHTSTRVL/harness_codex); if no source
directory is available, ask the user to choose or clone one rather than silently selecting
a personal fork or arbitrary repository.

For an existing Git clone, inspect its configured source before running the wrapper:

```text
git -C <repo> remote -v
git -C <repo> branch --show-current
git -C <repo> rev-parse --abbrev-ref --symbolic-full-name '@{u}'
```

If it tracks a fork or custom source, report that fact and leave the remote unchanged.
From the clean `<repo>` root, run `.\scripts\sync.ps1` on Windows or `bash scripts/sync.sh`
on macOS. These wrappers use the current branch's configured tracking remote and branch,
run `git pull --ff-only`, then apply the local installer. They do not support ZIP
auto-update and do not run setup-check automatically. Afterward, run
`python <repo>/scripts/setup-check.py` to verify the local installation.

The normal setup check is offline and reports the canonical public repository without
checking its latest revision. For an explicit public comparison, run
`python <repo>/scripts/setup-check.py --check-updates`. It asks the canonical `main` ref
for its tip and compares it with the Git checkout's committed root `HEAD`, reporting equal,
different or unknown without an ancestry claim. Working-tree edits are outside that
comparison. A ZIP has no Git history: local setup-check remains available, while the
public comparison is unknown.

To move a ZIP installation to Git, keep the extracted directory intact and clone the
[public repository](https://github.com/ARCLIGHTSTRVL/harness_codex) into a new destination,
then run its onboarding preview, apply and setup-check. Do not re-initialize the ZIP
directory, overwrite an existing destination or retarget a fork/custom remote
automatically. No SSH configuration or automatic peer propagation is managed.
