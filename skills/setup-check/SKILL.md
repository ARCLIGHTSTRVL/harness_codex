---
name: setup-check
description: Read-only community source, installed policy, skill and hook verification.
---

# setup-check

Read `source_repo` first from `CODEX_HOME/dev-setup-codex-community-state.json` (default
`CODEX_HOME` is `~/.codex`) and use that existing source directory as `<repo>`. If state
is absent or stale, inspect the supplied/current community checkout. The canonical public
source is [public repository](https://github.com/ARCLIGHTSTRVL/harness_codex); if no source
directory is available, ask the user to choose or clone one rather than silently selecting
a personal fork or arbitrary repository.

Run `python <repo>/scripts/setup-check.py` from any working directory and report content
drift. This command is read-only: it does not install, pull or alter the source. `--home`
selects a profile root; `CODEX_HOME` overrides the Codex directory. `--probe-hooks` executes
exact command probes only. Configuration, trust and host event delivery are separate facts.
ZIP installs need no Git history for this local status check.

The default check is offline. It prints the canonical public repository and states that
the latest public revision was not checked. Use `python <repo>/scripts/setup-check.py
--check-updates` only when an explicit public comparison is wanted. That opt-in query uses
`git ls-remote` for the canonical `main` ref, then compares its tip with the actual Git
checkout's committed root `HEAD`; it reports equal, different or unknown and makes no
ancestry claim. Working-tree edits are outside that comparison. For a ZIP source, the
local check still works and the public comparison is unknown.

If the user separately requests a ZIP-to-Git migration, suggest the following sequence;
setup-check itself remains read-only and does not clone or install. Leave the extracted
directory intact, then clone the canonical source into a new destination before running
onboarding from that clone:

```powershell
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git C:\path\to\harness_codex-git
python C:\path\to\harness_codex-git\scripts\onboard.py
python C:\path\to\harness_codex-git\scripts\onboard.py --apply
python C:\path\to\harness_codex-git\scripts\setup-check.py
```

```bash
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git /path/to/harness_codex-git
python3 /path/to/harness_codex-git/scripts/onboard.py
python3 /path/to/harness_codex-git/scripts/onboard.py --apply
python3 /path/to/harness_codex-git/scripts/setup-check.py
```

Do not re-initialize the ZIP directory, overwrite an existing destination or change a
fork/custom remote automatically. SSH and credentials are not managed.
