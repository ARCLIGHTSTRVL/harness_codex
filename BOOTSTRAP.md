# Fresh machine

Install Codex, Python 3.11+, and Git using your platform's supported installer.
On Windows, include Git Bash when installing Git. Do not use sudo for this bundle.
Download and extract the source package, install requirements.txt, and follow README.md.
Use your own Codex account and select models available to that account.

If you maintain a Git-hosted copy, pass its URL explicitly:

```powershell
.\scripts\bootstrap-windows.ps1 -RepoUrl https://github.com/OWNER/REPOSITORY.git
```

```bash
REPO_URL=https://github.com/OWNER/REPOSITORY.git bash scripts/bootstrap-mac.sh
```

These URLs are placeholders. No remote is created by this package.
