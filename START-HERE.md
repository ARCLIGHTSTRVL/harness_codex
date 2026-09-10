# Install this bundle with Codex

Give Codex access to the extracted folder and paste this request:

> Install this harness_codex bundle for my current user. Read START-HERE.md.
> Check the environment and show the target files first. Then apply the installation,
> verify setup-check, and tell me whether I still need to trust hooks or reopen Codex.
> Preserve my credentials, model choices, unrelated instructions and skills. Do not
> publish anything or configure another machine. Do not claim hooks ran unless observed.

한국어 요청문:

> 이 폴더의 harness_codex를 현재 사용자용으로 설치해 줘.
> START-HERE.md를 읽고 환경과 변경할 파일을 먼저 보여 준 다음 설치하고 검증해 줘.
> 내 계정, 모델 설정, 관련 없는 지침과 스킬은 보존해 줘.
> 훅 신뢰 설정이나 Codex 재시작이 필요하면 알려 주고, 실제 실행 여부는 구분해 줘.

The canonical public source is
[public repository](https://github.com/ARCLIGHTSTRVL/harness_codex). For an
initial Git install, clone it into a new permanent destination before following the
receiver procedure:

```powershell
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git C:\path\to\harness_codex
Set-Location C:\path\to\harness_codex
```

```bash
git clone https://github.com/ARCLIGHTSTRVL/harness_codex.git /path/to/harness_codex
cd /path/to/harness_codex
```

If you started from **Download ZIP** and want Git updates, leave the extracted folder in
place and clone the public source into a new destination, then run the preview, apply and
verification commands below from that clone. Do not run `git init` in the ZIP folder,
overwrite an existing destination or change a fork/custom remote automatically.

## Receiver procedure

1. Keep the extracted folder in a permanent, writable location. Do not install from
   a temporary attachment viewer. Installation scripts and hooks refer to this folder.
2. Use Python 3.11+ and Git. Windows needs Git Bash for project hook templates.
   If Python is unavailable, install it using the platform's trusted installer first.
3. From this folder, run `python scripts/onboard.py` (`python3` on macOS as needed).
   This checks prerequisites and prints the installation targets without changing them.
4. Run `python scripts/onboard.py --apply`. If PyYAML is missing, this creates a private
   `.runtime` virtual environment and installs requirements there. No global pip changes.
   Later installer/sync entrypoints reuse a valid dependency runtime. Status checks
   read the installation's interpreter from state, so ordinary Python can run them.
   Private dependency setup ignores pip configuration files and destination overrides.
   If a custom package index is required, supply it through pip's index environment
   settings; ordinary proxy environment settings remain available.
5. Verify `python scripts/setup-check.py`. Review/trust exact hook definitions through
   the host's hook UI (`/hooks` where supported), then reopen a session if needed to load
   the installed skills. File verification is distinct from runtime activation.

For a ZIP source, this local check does not require Git. A normal check is offline; use
`python <repo>/scripts/setup-check.py --check-updates` only when you explicitly want to
compare the public `main` tip with a Git checkout's root `HEAD`. The comparison reports
equal, different or unknown and makes no ancestry claim. Keep the ZIP directory until the
new clone's installation and hook source have been verified.

An explicit request to install authorizes running the installer. Repository maintenance
instructions do not prohibit this receiver workflow. Installation does not authorize
publishing, creating a remote, changing account settings or initializing unrelated projects.

## Add the knowledge workflow to a project

Run `python scripts/init-knowledge.py /absolute/path/to/project` for a preview, then
add `--apply`. This adds only missing knowledge directories, indexes, an empty unit
registry and fresh handoff metadata. Existing project files are preserved.
Add `--hooks` to include missing project-local hook templates. Existing hook definitions
are not overwritten; Codex should inspect and merge them when needed, then explain trust.
Use the project-init skill for full project-specific AGENTS/wiki conventions.

The agent captures and distills knowledge. Scripts validate/apply/archive the results.
Hooks preserve saved handoff state; they do not summarize unrecorded conversations.

## Undo installation

Preview the latest rollback:

```text
python scripts/install.py rollback --home USER_HOME --repo THIS_FOLDER --platform windows
```

Use `mac` on macOS. Replace USER_HOME and THIS_FOLDER with absolute paths. CODEX_HOME,
when set, selects the target Codex directory. Add `--apply` to restore the displayed files.
Use `uninstall` instead of `rollback` to restore the baseline before all recorded installs.
If a target changed after installation, recovery refuses before writing; inspect the
named files and their snapshots, then reconcile the edits. There is no force overwrite.
Edits made between upgrades also prevent a combined uninstall; roll back one version
at a time to recover the intermediate user-edited version without discarding it.

Recovery history remains local in `dev-setup-codex-community-recovery.json` under
CODEX_HOME, alongside the install state. It contains original file bytes; never share it.
New installations also preserve allowlisted execution source under
`dev-setup-codex-community/sources/` in CODEX_HOME. Rollback connects restored hooks to
that source without rewriting your Git checkout. The state retains the original checkout
as `update_repo` for the next sync. Keep the recorded Python runtime available;
source snapshots do not include virtual-environment binaries. Missing or modified
recovery source blocks rollback before target changes. Older state without a source
snapshot can be restored only while its original source still matches the recorded hash.
Backups and native runtime records are retained after uninstall. A pre-0.1.1 installation
has no original recovery baseline: rollback can restore that version, but a full removal
requires its earlier backups. An interrupted process without a complete post-write record
also requires inspection of saved originals; the tool will not guess.
