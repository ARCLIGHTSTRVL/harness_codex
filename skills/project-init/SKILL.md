---
name: project-init
description: Initialize a new durable direct-Codex project with AGENTS.md, NEXT.md, wiki/, knowledge/, workflow/, and optional .codex hooks. Use for "new project init", "project bootstrap", "새 프로젝트 초기화", "프로젝트 부트스트랩".
---

# project-init

Create a new project using the Codex-native bootstrap checklist. This is
mutating: it creates files in the target project and may initialize git/GitHub
when the user asks for that.

## Procedure

1. Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json` (default CODEX_HOME is `~/.codex`). Use that source directory as `<repo>`. Without state, locate the extracted community directory supplied by the user; never guess a personal repository.
2. Read `<repo>/templates/new-project-init.md` fully before taking action.
   For an existing project, `python <repo>/scripts/init-knowledge.py <project>`
   previews missing knowledge scaffolding. Add `--apply` and optionally `--hooks`
   after the requested scope is clear; existing project files are preserved.
3. If the user has not already answered the intake, ask only the missing
   questions from the checklist.
4. Execute the checklist in order. Do not clobber existing project files without
   showing the conflict and getting explicit confirmation.
5. Use the project-owned files as authority after creation:
   - root `AGENTS.md`
   - root `NEXT.md`
   - `wiki/SCHEMA.md`
   - `knowledge/SCHEMA.md`

## Boundaries

- Do not create `CLAUDE.md` or `.claude/` by default.
- Do not silently create a public GitHub repo.
- Do not bulk-translate knowledge into Obsidian; KR mirrors are hand-made on
  request.
- Hook templates are seed-and-own. If copied, tune both `stop-handoff-gate.sh`
  and `compact-handoff-gate.sh` to the project's stack from the checklist's
  work-glob presets before relying on them.
- Hook templates pin Windows Git Bash through `OMO_CODEX_GIT_BASH_PATH` or
  `%ProgramFiles%/Git/bin/bash.exe`, never bare `bash` on PATH. Preserve
  `commandWindows` entries, including `exit $LASTEXITCODE`, before treating them
  as active protection.
- Project-local Codex hooks are not durable protection until the user reviews
  and trusts their exact definitions with `/hooks` after merging/tuning or later
  edits.
- Fill `NEXT.md` from the template before relying on hooks. Root `NEXT.md` is
  handoff metadata and must not be listed in `unit_paths`; use
  `templates/NEXT.md` only when the template itself is the work.
- Keep NEXT within the default 60-line Stop budget. The budget has its own
  once-per-session nudge, independent of whether NEXT was updated.
- Seed `plan-handoff.py` alongside shell hooks for saved active-plan recovery
  at SessionStart. Use `templates/plan-file.md` for multi-session or 3+ phase
  work; keep its unique literal Handoff marker pair. This is saved-state
  recovery, not proof of live automatic-compaction delivery.
