# New Project Init Checklist

Use this when starting a durable project that should survive cold-started Codex
sessions, machine moves, and long gaps between work. Output: a fully wired
`<project>/` directory with `AGENTS.md`, `NEXT.md`, `wiki/`, `knowledge/`,
`workflow/`, optional `.codex` bootstrap hooks, and an initial commit.

This is a Codex-native port of the original Claude-oriented project bootstrap:
the functionality stays, but `CLAUDE.md` / `.claude` surfaces are replaced with
direct Codex `AGENTS.md` / `.codex` equivalents.

## Five-Question Intake

Ask these once per new project. Do not reuse answers from a previous project.

1. **Stack / domain** - what kind of project.
   - Examples: "Python ML training, multimodal embeddings" / "Electron desktop,
     audio playback console" / "React + FastAPI tracker"
   - This drives wiki tag taxonomy and Stop/PreCompact hook work globs.

2. **Solo permanent vs team / OSS-able** - how strict the project should be.
   - Solo permanent: lighter frontmatter, KR-friendly local notes OK.
   - Team / OSS-able: stricter schema, full frontmatter, lint in review, English
     public docs.
   - Default if unsure: team / OSS-able. It is easier to relax later.

3. **Wiki language** - prose language for `<project>/wiki/`.
   - Default: English. It is concise and works well for AI-facing code notes.
   - Korean is allowed when the user explicitly wants the wiki itself in Korean.

4. **Repo path + project name** - canonical location and name.
   - Path convention: `C:\dev\<name>\` on Windows, `~/dev/<name>` on Mac.
   - Name convention: lowercase, alphanumerics + dash, full words, no
     underscores or spaces.

5. **Git / GitHub** - version control and visibility.
   - Git is strongly recommended; `NEXT.md` freshness and wiki pins depend on
     commit identity.
   - Common answer: GitHub private, e.g. `<owner>/<name>`.
   - Public from day 1 means stricter schema and confidence/provenance.
   - No-git disables the strongest freshness checks and is not recommended for
     durable work.

## Init Procedure

Execute in order after intake answers are known.

### 1. Repo + Git

```bash
mkdir <repo-path>
cd <repo-path>
git init -b main
gh repo create <owner>/<name> --private --source . --remote origin
```

Use `--public` only when the user explicitly wants a public repo.

Create `.gitignore` before the first `git add .`:

```bash
printf '.ask-artifacts/\n.env\n*.pfx\n*.pem\n*.key\nauth.json\n.codex/.stop-warned-*\n.codex/.compact-warned-*\n.codex/.last-doctor\n.codex/.last-health\n' > .gitignore
```

On Windows PowerShell, create the same content with explicit UTF-8 encoding:

```powershell
@'
.ask-artifacts/
.env
*.pfx
*.pem
*.key
auth.json
.codex/.stop-warned-*
.codex/.compact-warned-*
.codex/.last-doctor
.codex/.last-health
'@ | Set-Content -Encoding utf8 .gitignore
```

Create `.gitattributes` before copying hook scripts so Windows line-ending
normalization cannot make `.sh` hooks dirty or non-portable:

```bash
cat > .gitattributes <<'EOF'
* text=auto
*.sh text eol=lf
*.md text eol=lf
*.json text eol=lf
*.py text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
EOF
```

On Windows PowerShell:

```powershell
@'
* text=auto
*.sh text eol=lf
*.md text eol=lf
*.json text eol=lf
*.py text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
'@ | Set-Content -Encoding utf8 .gitattributes
```

### 2. Project Skeleton

```text
<project>/
├── AGENTS.md           # Codex cold-start front door
├── NEXT.md             # single active handoff
├── README.md           # one-paragraph description from intake #1
├── .gitattributes      # line-ending contract for cross-platform hooks/docs
├── .codex/             # optional bootstrap hooks
│   ├── hooks.json
│   └── hooks/
├── workflow/
│   └── README.md
├── knowledge/
└── wiki/
```

Do not create `CLAUDE.md` or `.claude/` by default. This is a direct-Codex
project; Claude-specific files are opt-in only if a project also uses Claude
Code independently.

Seed `NEXT.md` from `templates/NEXT.md` and fill every placeholder before the
first commit. `last_verified_commit` is the latest commit whose unit state and
pointers were verified. Do not list the root `NEXT.md` in `unit_paths`; it is
handoff metadata, and including it makes handoff-only commits self-invalidating.
If the NEXT template itself is the work, list `templates/NEXT.md`.

### 3. Wiki Init

Follow `~/.codex/skills/codebase-wiki/references/initialization.md`.

Customize it from the five answers:

- `wiki/SCHEMA.md`: project/domain summary, discipline level, wiki language,
  and git SHA pin policy.
- Tag taxonomy: 10-20 project-specific tags plus a `meta` group for
  architecture, decision, comparison, and ADR pages.
- Required page templates: entity, concept, comparison, query.
- Pin policy: symbol pins preferred; range pins as fallback; file-level pins
  only as a last resort.
- Stale layers: Layer 1 always on; Layer 2 recommended; Layer 3 threshold
  default 50 commits unless project risk says otherwise.
- `wiki/index.md`: sectioned empty shell.
- `wiki/log.md`: first entry:
  `## [YYYY-MM-DD] create | Wiki initialized`
- `wiki/AGENTS.md`: static routing guide for agents that land inside `wiki/`.

### 4. Knowledge Init

Seed `knowledge/` during project creation so `research-kb` and
`knowledge-fragment` are available from day one.

1. Follow `~/.codex/skills/research-kb/SKILL.md` operation `init`.
   It creates `knowledge/SCHEMA.md`, `knowledge/index.md`, `knowledge/log.md`,
   and the research KB subdirectories.
2. Customize the tag taxonomy in `knowledge/SCHEMA.md` for this project's domain.
3. Create `knowledge/_fragments/units.yml` from `templates/knowledge-units.yml`:

   ```yaml
   # knowledge-fragment unit registry - canonical id + aliases.
   # Capture MUST pick an existing canonical_id before coining a new slug.
   ```

4. Verify these exist:
   - `knowledge/SCHEMA.md`
   - `knowledge/index.md`
   - `knowledge/_fragments/units.yml`

### 5. Workflow Init

Create `workflow/README.md` with:

- current phase or "not started"
- where status will live (`workflow/status.md` when the first phase begins)
- what belongs in workflow vs `NEXT.md`

Rule: `NEXT.md` owns the single next action. `workflow/` owns broader phase
state. If they conflict, treat `NEXT.md` as the current intent only after the
freshness check passes.

When a unit spans sessions or has at least three separately verified phases,
seed `workflow/plans/<canonical_id>.md` from `templates/plan-file.md`. Keep the
plan's literal Handoff markers and `status: active`; update it before pauses.
Do not include `workflow/plans/` in NEXT `unit_paths`. At closure, record the
verified results in knowledge and remove the completed plan and its NEXT entry.

### 6. Cold-Start Bootstrap

Seed the root files:

- Copy `templates/AGENTS.md` from this repo to `<project>/AGENTS.md`, then fill
  the project-specific sections from the intake answers.
- Copy `templates/NEXT.md` to `<project>/NEXT.md`, then seed the first active
  work unit.
- Set `last_verified_commit` to the current commit after the first successful
  verification. Before the first commit, use `UNCOMMITTED` and update it after
  the initial commit.
- Set `unit_paths` to concrete repo-relative paths for the active unit. Do not
  use globs or paths with spaces; the freshness hook treats ambiguous paths as
  unverifiable.

### 7. Optional `.codex` Hooks

Recommended for projects meant to survive long gaps or repeated agent sessions.
These are seed-and-own: the project owns its copy after initialization.

1. Copy:
   - `templates/hooks/freshness-inject.sh` ->
     `<project>/.codex/hooks/freshness-inject.sh`
   - `templates/hooks/plan-handoff.py` ->
     `<project>/.codex/hooks/plan-handoff.py`
   - `templates/hooks/compact-handoff-gate.sh` ->
     `<project>/.codex/hooks/compact-handoff-gate.sh`
   - `templates/hooks/stop-handoff-gate.sh` ->
     `<project>/.codex/hooks/stop-handoff-gate.sh`
   - `templates/hooks.json` -> `<project>/.codex/hooks.json`
2. If the project already has `.codex/hooks.json`, merge the hook arrays
   instead of overwriting.
3. On Mac/Linux, run:
   ```bash
   chmod +x .codex/hooks/*.sh
   ```
4. On Windows, these hook templates pin Git Bash using `OMO_CODEX_GIT_BASH_PATH`
   or `%ProgramFiles%/Git/bin/bash.exe`; they do not select `bash` from `PATH`.
   Verify that the selected executable exists, and keep the
   `commandWindows` entries, including `exit $LASTEXITCODE`, in `.codex/hooks.json`
   when merging project-specific hooks.
   Verify `python --version` or `python3 --version` (Python 3.10+) for saved
   plan recovery. Freshness invokes `plan-handoff.py` at SessionStart, including
   `source=compact`; PreCompact retains the separate handoff gate. Run the reader
   directly against a temporary active plan to verify saved Handoff output.
   These project gates complement the installer's global health, compact-carry
   and native-agent hooks; neither layer's configuration proves host delivery.
5. Derive the work globs from intake #1, then apply the same `case "$p" in`
   pattern line to both `stop-handoff-gate.sh` and `compact-handoff-gate.sh`.
   The template default covers common mixed repos:
   `workflow/*|scripts/*|src/*|app/*|lib/*|tests/*|test/*|docs/*|.github/*|*.py|*.js|*.jsx|*.ts|*.tsx|*.rs|*.go|*.md|*.json|*.toml|*.yaml|*.yml|package.json|package-lock.json|pnpm-lock.yaml|yarn.lock|Cargo.toml|Cargo.lock|go.mod|go.sum|pyproject.toml|requirements*.txt|uv.lock|poetry.lock|Dockerfile|docker-compose*.yml`.
   Use it only when it matches the project. Otherwise replace it with a stack
   preset before relying on the hooks:
   - Python / ML: `workflow/*|scripts/*|src/*|tests/*|notebooks/*|configs/*|*.py|*.ipynb|*.yaml|*.yml|*.toml|pyproject.toml|requirements*.txt|uv.lock|poetry.lock`
   - JS / TS / Electron: `workflow/*|scripts/*|src/*|app/*|components/*|tests/*|test/*|*.js|*.jsx|*.ts|*.tsx|*.json|*.css|*.html|package.json|package-lock.json|pnpm-lock.yaml|yarn.lock`
   - Rust / Go: `workflow/*|src/*|crates/*|cmd/*|pkg/*|tests/*|*.rs|*.go|Cargo.toml|Cargo.lock|go.mod|go.sum`
   - Docs / research: `workflow/*|docs/*|wiki/*|knowledge/*|*.md|*.mdx`
   - Mobile: `workflow/*|app/*|src/*|ios/*|android/*|lib/*|tests/*|*.swift|*.kt|*.java|*.dart|*.ts|*.tsx`
6. After merging and tuning the final hook definitions, run `/hooks` from the
   project in Codex and review/trust the copied project-local hooks. Copying
   `.codex/hooks.json` is not enough; new or changed non-managed hooks can be
   skipped until Codex has an exact trusted definition.
7. Keep `.codex/.stop-warned-*`, `.codex/.compact-warned-*`,
   `.codex/.last-doctor`, and `.codex/.last-health` gitignored.
8. Use `python <dev-setup-codex>/scripts/bootstrap-doctor.py` later to see
   which project copies are outdated.

### 8. Obsidian / KR Mirror

No per-project Obsidian link is required at init. If the user wants a Korean
mirror of `knowledge/` for deep reading, generate it by hand on request via
`knowledge-mirror`. Do not bulk-translate the knowledge base.

### 9. First Commit

```bash
git add .
git commit -m "Initialize <name>: <one-line domain>"
git push -u origin main
```

After the commit, update `NEXT.md`:

- replace `last_verified_commit: UNCOMMITTED` with the new commit SHA
- update `last_touched`
- commit that handoff update if needed

## Boundaries

- `AGENTS.md` - project-local Codex instructions and cold-start routing.
- `NEXT.md` - one active unit; current handoff, not a backlog.
- `workflow/` - broader phase/status tracking.
- `wiki/` - code mechanics and architecture, terse and source-pinned.
- `knowledge/` - research intellect: findings, decisions, experiments.
- `knowledge/_fragments/` - transient per-session deltas before consolidation.
- Obsidian - optional Korean reading mirror, hand-made and derivative.

## When Not To Use This Checklist

- Throwaway scripts with a lifespan under roughly one week.
- Very small tools where wiki/knowledge overhead exceeds value.
- Greenfield experiments where the domain is still unknown. Start lighter and
  add the bootstrap when the project stabilizes.

## Related References

- `templates/AGENTS.md`
- `templates/NEXT.md`
- `templates/hooks.json`
- `templates/hooks/freshness-inject.sh`
- `templates/hooks/compact-handoff-gate.sh`
- `templates/hooks/stop-handoff-gate.sh`
- `~/.codex/skills/codebase-wiki/references/initialization.md`
- `~/.codex/skills/research-kb/SKILL.md`
- `~/.codex/skills/knowledge-fragment/SKILL.md`
- `specs/project-bootstrap-continuity.md`
