# Fresh machine

Install Codex, Python 3.11+, and Git using your platform's supported installer.
On Windows, include Git Bash when installing Git. Do not use sudo for this bundle.
Download and extract the source package and follow README.md's onboarding procedure.
Use your own Codex account and select models available to that account.

The canonical public source is
[public repository](https://github.com/ARCLIGHTSTRVL/harness_codex). For a fresh Git
checkout, clone it into a new permanent destination:

```powershell
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git C:\path\to\harness_codex
```

```bash
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git /path/to/harness_codex
```

From the extracted bundle's root, run the bootstrap wrapper with the canonical URL:

```powershell
.\scripts\bootstrap-windows.ps1 -RepoUrl https://github.com/ARCLIGHTSTRVL/harness_codex.git
```

```bash
REPO_URL=https://github.com/ARCLIGHTSTRVL/harness_codex.git bash scripts/bootstrap-mac.sh
```

When the target already exists, the wrapper uses that checkout's configured tracking
remote and branch; it does not retarget a fork or custom source from the URL argument.
Inspect the target first and choose a new destination when a public clone is wanted. For a
ZIP-to-Git update, leave the ZIP directory intact, clone the canonical source into a new
destination and run its onboarding preview, apply and setup-check. Do not re-initialize
the ZIP directory or overwrite an existing destination. Account, model and SSH settings
remain under the recipient's control.
