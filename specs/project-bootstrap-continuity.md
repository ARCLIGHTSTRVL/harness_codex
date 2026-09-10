# Project bootstrap & continuity — decision record

## Codex port note

This file started as the Claude-oriented design record. In this Codex-native
repo, the implemented project bootstrap surface is:

- project root `AGENTS.md`, seeded from `templates/AGENTS.md`
- project root `NEXT.md`, seeded from `templates/NEXT.md`
- optional project `.codex/hooks/*` plus `.codex/hooks.json`
- `templates/new-project-init.md` as the executable checklist
- `project-init` as the skill entrypoint

Historical sections below may say `CLAUDE.md` / `.claude` because they preserve
the original reasoning. For direct-Codex project creation, follow
`templates/new-project-init.md`; it is the current operational authority.

How an agent resumes a project across **dual amnesia**: the human forgets after weeks,
and the agent resets its context every session and carries nothing but files. The only
shared memory between sessions is what is written to disk. This record captures the design
arrived at over a multi-turn design conversation (2026-05-31 — 2026-06-01), the adversarial
review that hardened it, and what remains open.

Companion to `specs/deep-interview-knowledge-base.md` (the research-KB convention). That
spec governs *what we learned*; this one governs *how a cold-starting agent finds its place
and continues*.

## Problem

Project state had drifted toward the global `~/.claude` memory store (compressed pointers,
AI-facing). That is a single point of failure: reinstalling Claude, or losing the memory
files, erases every project's working memory. It also means a fresh agent started **from a
project directory** does not get enough from the project alone to continue.

Goal: an agent cold-starting from the project dir with **zero prior context** obtains enough
**from the project dir alone** to safely continue the next work unit.

**Litmus test:** *if losing `~/.claude` prevents the agent from continuing the project, that
information is in the wrong place.* Project **state** lives in-repo; the global layer stays
thin.

## The decision

1. **Decentralize project state into the repo.** Global `~/.claude` keeps only: user
   prefs / working style, machine paths, tool quirks, cross-project habits, policy defaults,
   and a thin project registry (name + path + one-line status) used only to *find* projects.
2. **`CLAUDE.md`-only entry; `AGENTS.md` dropped from projects.** Claude is always the
   orchestrator and the information hub. `AGENTS.md` is Codex's file and is not natively
   read by Claude Code; Codex is fed context via the prompt and does not read the project
   dir. So a project carries no `AGENTS.md` — the single auto-loaded root `CLAUDE.md` is the
   front door. (This corrected an earlier over-engineering that proposed an `AGENTS.md`-canonical
   file with a `CLAUDE.md` `@import`.)
3. **One authoritative source per fact.** `NEXT.md` is authoritative for "the next action";
   `workflow/status.md` is broad current state; on conflict, `NEXT.md` wins. KR Obsidian
   mirrors are read-only derivatives (carry source file + commit + generated timestamp).

## The bootstrap pattern (per project)

### Root `CLAUDE.md` — the cold-start front door (auto-loaded)

Thin, kept lean (~200-line budget; routing lives here until it outgrows the budget). It
contains, in order:

- one-line orientation (what the project is + "Claude = orchestrator, info hub");
- **read order** — `NEXT.md` first, then the one-line indexes (`wiki/index.md`,
  `knowledge/index.md`, `workflow/PROJECT_MAP.md`), then **only the 1–2 pages** those point
  to. Explicit prohibition: *do not slurp the whole KB.* Just-in-time, index-first.
- the **freshness-check procedure** (below) — run before trusting `NEXT.md`;
- layer routing (which question → which layer);
- build / run / data commands;
- prohibitions (e.g. a read-only original tree).

### `NEXT.md` — the handoff (single-writer)

**One** active work unit, not a backlog. Frontmatter: `last_verified_commit`,
`last_touched`, `writer`, `unit_paths`. Body: active-unit goal, current state,
blocker, `file:line` pointers, acceptance criteria, and a "pending (not this
unit)" tail for deferred gates.

`last_verified_commit` means the latest commit whose unit state and pointers
were actually verified. It can be behind `HEAD` when later commits only update
handoff metadata. The root `NEXT.md` must not appear in `unit_paths`; otherwise
the handoff commit self-invalidates. If the NEXT template is the actual work,
pin `templates/NEXT.md`, not the root handoff file.

### In-repo layers as routing targets

- `wiki/` — how the code works (terse, AI-facing; symbol-pins + commit SHA; wiki-lint).
- `workflow/` — current phase/context (`status.md` = broad state).
- `knowledge/` — research findings & decisions (full-fidelity, human-facing; KR mirror in
  Obsidian DEV vault). Each layer has an `index.md`.

## Git-truth freshness check (the adversarially-hardened core)

`NEXT.md` can lie: the writing session may have died mid-work, or the history may have been
rebased / squashed / force-pushed / branch-switched since it was written. A **convention**
("keep NEXT.md current") is not enough — the check must be an **executable** git
computation. The cold-start agent runs this **before** presenting `NEXT.md` as fact:

1. `git merge-base --is-ancestor <NEXT.last_verified_commit> HEAD` → **fails** (not an
   ancestor: squash/rebase/force-push/branch-switch) ⇒ `NEXT.md` suspect; ignore its
   `file:line` and re-derive from `workflow/status.md` + `git log --oneline -20`.
2. `git log <last_verified>..HEAD -- <paths NEXT points to>` → **unit-scoped delta**.
   Commits on the unit's paths ⇒ that part is stale. The repo moving on *unrelated* paths
   must **not** raise a false alarm. *(This — not the ancestry check — is the real signal;
   `--is-ancestor` is near-decorative because `last_verified` is almost always an ancestor.)*
3. `git status --porcelain` non-empty ⇒ inspect the diff. If uncommitted
   changes touch `unit_paths`, report WIP and inspect the diff. This is work in
   flight, not evidence that commits overtook the handoff. Missing paths,
   ancestry failures or committed unit changes still independently make NEXT
   STALE. Dirt outside `unit_paths` is a context warning.
4. `NEXT.last_touched` older than ~7 days ⇒ a **hint only**; never flips the verdict.
5. If `workflow/status.md`, `workflow/README.md`, `wiki/log.md`, `wiki/index.md`,
   `knowledge/log.md`, or `knowledge/index.md` changed since `last_verified_commit`, keep
   the verdict FRESH when the unit checks passed, but append a WARN: semantic project
   context moved after the handoff.

**Fail-safe:** STALE/UNVERIFIED must not be presented as verified state. WIP
requires inspecting the current diff and active plan before resumption.
Say "the handoff looks stale (reason), re-deriving", read `workflow/status.md` + recent
`*/log.md`, and confirm the next unit with the user. Demoting a stale-NEXT to **NO-NEXT** is
strictly better than following a wrong-NEXT.

## Operational enforcement — hooks (command-hooks only)

A `CLAUDE.md` instruction is advisory; Claude Code **hooks** make the freshness discipline
deterministic. Reviewed 2026-06-01 against the current official hooks docs + practitioner
patterns + an adversarial pass (workflow `hooks-upgrade-review`). **Decision: deterministic
command hooks only.** The newer prompt-based / agent-based (model-in-the-loop) hooks *regress*
reliability here.

Why not model-in-the-loop:

- **prompt-based hooks fire on `Stop`/`SubagentStop` only**, and their contract is a
  yes/no + reason — there is **no `additionalContext` injection path**. SessionStart context
  injection is a *command-hook* capability (stdout / `hookSpecificOutput.additionalContext`).
  So the SessionStart freshness hook is structurally a command hook.
- **agent-based hooks are experimental** (docs: "for production workflows prefer command
  hooks"), add a 60s / up-to-50-turn subagent per event, and can return a wrong verdict.
- official rule of thumb: *"do not use prompt-based hooks for safety boundaries — they are
  probabilistic; for hard safety constraints use deterministic command hooks."* Freshness is
  a git fact, not a judgment.

The Codex port ships three project-local command hooks:

- **A — SessionStart freshness inject** (matcher `startup|resume|clear|compact`): a command hook
  runs the git-truth check and injects the verdict ("NEXT FRESH @\<commit\>" /
  "NEXT STALE: \<reason\> — re-derive" / "NEXT UNVERIFIED — re-derive"). Replaces the current
  hardcoded-stale `compact-context.sh`. The emitted prefix includes the hook source
  (for example, `[freshness source=compact]`) so automatic-compaction re-entry is visible.
- **A2 — PreCompact handoff gate** (matcher `manual|auto`): automatic Codex compaction can
  happen before an agent reaches Stop, so this command hook gives one session-scoped nudge
  to update `NEXT.md` before context is summarized. It is a guardrail, not the durable store;
  the durable state still lives in `NEXT.md`, `workflow/`, `wiki/`, and `knowledge/`.
- **B — Stop enforcement**: a command hook blocks the agent from ending (exit 2) iff real
  work happened (git delta touches `workflow/`/`scripts/`/training code) **and** the handoff
  did not advance (`NEXT.md` not in the changed set / `last_verified_commit` unchanged).
  Replaces the buggy warn-only `check-status-update.sh`.

**Must-haves if built (from the adversarial pass F1–F6):**

- **F1 / bash-provider ambiguity (CRITICAL):** two `bash.exe` on PATH (git-bash vs WSL
  `System32\bash.exe`); under WSL, `git -C 'C:\...'` fails. Hard-pin the interpreter,
  `set -euo pipefail`, normalize the path (`cygpath`), and **fail CLOSED** — the last
  possible output is "UNVERIFIED", never "fresh".
- **F2:** drive the verdict off the **unit-path `git log` delta being empty**, not off
  `--is-ancestor`; treat a path-not-found as STALE.
- **F3:** Stop hook = **one nudge max per session** — `session_id` sentinel file +
  `stop_hook_active` guard; if the sentinel write itself fails, `exit 0` (never block when
  you cannot guarantee you can un-block). `stop_hook_active` *is* documented (guide,
  "block cap" section) but bug #55754 shows it is not always honored — hence the sentinel.
- **F5:** roll A out in **unverified-only mode first** (never emit "fresh" until the git
  logic is proven on a real `NEXT.md`). Historical pilot note: at that point SessionStart
  only fired on `compact`, so the stale blurb rarely injected; the direct-Codex template
  now matches `startup|resume|clear|compact`, which raises blast radius and requires terse
  FRESH output.
- **F6:** `last_touched` age is a note, never flips the verdict.

Also fix while in there: `check-doc-consistency.sh` (3 of 4 trigger filenames are dead) and
the `check-status-update.sh` uppercase-`STATUS.md` grep + unstaged-only `git diff` bugs.

**Built (2026-06-01, Hibiki pilot `C:\dev\hibiki_restructure`, commits `b956db9` + `9fba6de`).**
`freshness-inject.sh` (SessionStart `startup|resume|clear|compact`) and `stop-handoff-gate.sh` (Stop)
replace the stale `compact-context.sh` / buggy `check-status-update.sh`. Implementation vs the
F-list: F1 path-normalize via `cygpath`/`wslpath` + fail-closed — `set -uo pipefail` with an
explicit UNVERIFIED emit on every error path (chosen over `set -e` so no error exits silently);
F2 verdict driven by unit-path existence + `git log` delta, with a machine-readable `unit_paths:`
frontmatter field added to `NEXT.md`; F3 `session_id` sentinel + `stop_hook_active` guard, no-block
if the sentinel can't be written; F5 a `TRIAL` flag frames FRESH as advisory; F6 age is a note. A
Codex Mode 3 review (ship-with-changes; it confirmed **no Stop-loop** in the stable-session path)
drove fail-closed / under-block fixes: FRESH now *requires* `unit_paths` (else UNVERIFIED),
git-command failures emit UNVERIFIED, `set -f` disables glob expansion, and the Stop gate detects
**untracked** new files via `git status --porcelain` (not `git diff`) with `core.quotePath=false -z`
so non-ASCII paths aren't missed, matching the exact repo-root `NEXT.md`. Verified across 12
scenarios (FRESH / STALE-ancestor / STALE-missing-path / dirty / no-unit_paths→UNVERIFIED /
untracked-work→block / Korean-path→block / NEXT-updated→no-block / re-entry + sentinel guards).
**Codex port amendment (2026-06-29):** the operational template is now `.codex/hooks.json`
instead of the Claude-era `.codex/settings.json` surface. Each command hook has a POSIX
`command` and a Windows `commandWindows`; both resolve the git root and
then run the project-owned `.codex/hooks/...` script. The September 2026 Windows
launcher pins `OMO_CODEX_GIT_BASH_PATH` or `%ProgramFiles%/Git/bin/bash.exe`, passes
the root as an argument, and uses explicit native-path conversion for the Python
plan reader. It never selects the WSL `bash` shim from PATH. Windows commands must end with
`exit $LASTEXITCODE`; otherwise PowerShell can collapse bash `exit 2` into `1` and weaken
the Stop hook's block contract. This avoids POSIX/PowerShell/cmd quoting drift and keeps
subdirectory starts pointed at the copied project hooks. Because the copied hooks are
project-local non-managed Codex hooks, project init must include an explicit `/hooks`
review/trust step after merging and tuning the final definitions; file presence is not
the same as active hook execution. Still open: `check-doc-consistency.sh`'s
3 dead trigger filenames.

## Adversarial review (Codex, hostile design pass)

**Scope of this review (provenance).** Codex ran in a fresh `/ask` session — it carried no
conversation history, no memory, and was not pointed at the repo. It reviewed only a
self-contained textual design summary written into the prompt (goal + a 10-point structure +
constraints). So this is a **design-logic** review (does the design hold up in principle),
**not** a review of the repo or the implementation: it cannot vouch for repo-specific facts
(the Windows bash-provider ambiguity, the actual stale hook filenames, real git state) —
those were validated **separately** by the `hooks-upgrade-review` workflow, whose agent read
the real files on disk. The review also **predates two later refinements**: it saw an
"`AGENTS.md` / `CLAUDE.md`" design (before the CLAUDE.md-only decision) and the pre-fail-safe
freshness check. Dispositions in the table reflect decisions made *after* the review.

Verdict **ship-with-changes**. Meta-conclusion: *"the proposal relies on conventions where
it needs executable checks and explicit authority rules."* Findings and disposition:

| # | sev | finding | disposition |
|---|---|---|---|
| 1 | crit | auto-load behavior differs per tool/scope; cold-start from a subdir may never see the root file | **partial** — resolved by CLAUDE.md-only + Claude-primary; subdir-load caveat remains open |
| 2 | crit | `NEXT.md` single-writer is theory; `last_verified..HEAD` detects movement, not branch/worktree/task ownership | **partial** — adopted merge-base + dirty-tree; branch/worktree/task-id fields **deferred** |
| 3 | crit | memory→repo migration has no schema for rejecting secrets / machine-local / prefs | **deferred** — migration checklist not yet written |
| 4 | major | "self-invalidating = re-derive from git diff" is an underspecified recovery algorithm | **adopted** — fail-safe-to-NO-NEXT + ordered recovery (status → branch → recent commits → ask) |
| 5 | major | route tables rot semantically; pass "target exists" lint while pointing at obsolete docs | **deferred** — route-coverage lint not built |
| 6 | major | symbol-pins + SHA silently fail after renames/squash/splits | **deferred** — wiki-lint symbol-resolution + tombstone not built |
| 7 | major | multi-machine pointers in `NEXT.md` become lies (Windows-only path, WSL mount, Mac lag) | **deferred** — `environment/locations.md` + location-IDs not built |
| 8 | major | dual-truth (KR/EN, terse/full, workflow/knowledge) — which is authoritative? | **adopted** — one authoritative source per fact; mirrors carry source+commit+timestamp |
| 9 | minor | "central / 2+ units" threshold is subjective | **deferred** — objective thresholds not defined |
| 10 | minor | "START_HERE age" undefined (edit vs commit vs verified vs reviewed) | **partial** — `last_touched` defined; `last_human_reviewed`/`last_agent_verified` deferred |

## Pilot / dogfood status

Minimal version piloted on Hibiki (`C:\dev\hibiki_restructure`, staging — original
`project_hibiki` is read-only): root `CLAUDE.md` + `NEXT.md`, commit `12bdbd6`. **Litmus
passed** — the unit-scoped delta (check 2) correctly reported `NEXT.md` valid even though
HEAD had moved, because the moves were on paths the unit did not point to (no false alarm).
Hooks A/B are **built, verified (12 scenarios), and Codex-reviewed** on the pilot (commits
`b956db9` + `9fba6de`); see "Operational enforcement — Built" above.

## Open / deferred (for the next session)

Not yet adopted from the adversarial findings — the gaps a returning agent should know:

- `branch` / `worktree-root` / `task-id` / `base-commit` fields in `NEXT.md` (finding 2).
- `environment/locations.md` with host-qualified, freshness-checked location IDs; `NEXT.md`
  referencing location IDs instead of raw machine paths (finding 7).
- Lint extensions: route-coverage (finding 5), wiki symbol-pin resolution + tombstones
  (finding 6), mirror-staleness age (finding 8).
- Objective "central / scoped-context" thresholds (finding 9).
- `memory → repo` per-item migration checklist: classification, destination, sensitivity,
  owner, expiry, reviewer (finding 3).
- **M3** (WSL launch wrapper) — still deferred; revisit only if a WSL-only hook shell is used.
- Mac smoke-test of the seeded hooks — the templates are portable-by-construction (python3
  fallback, BSD-date fallback, cygpath/wslpath no-op off-Windows) but were only run on Windows
  git-bash (Mac was offline).
- `check-doc-consistency.sh`'s dead triggers — a **Hibiki-project** maintenance task, split out
  of the harness work (its content is project-specific, so not generalizable).

## How this applies to new projects (Codex-wired)

The pattern ships via the direct-Codex harness, not re-invented per project:

- Global `~/.codex/AGENTS.md` carries the always-on project bootstrap policy.
- `project-init` is the skill entrypoint for durable project creation.
- `templates/new-project-init.md` is the operational checklist.
- `templates/AGENTS.md` is the project-local cold-start front door.
- `templates/NEXT.md` seeds the single active handoff.
- `templates/hooks/freshness-inject.sh` + `templates/hooks/compact-handoff-gate.sh`
  + `templates/hooks/stop-handoff-gate.sh` + `templates/hooks.json` seed optional
  `.codex` hooks.
- **A-model / seed-and-own:** the project owns its copied hooks; template fixes do
  not auto-propagate.
- **Drift visibility:** each hook carries a `# bootstrap-hooks vN` stamp, and
  `bootstrap-doctor` (`scripts/bootstrap-doctor.py`) audits each project's seeded
  version vs the template plus tier (`docs-only`, `trial-hooks`,
  `enforced-hooks`) and `NEXT.md` presence. Upgrading is a deliberate re-copy
  that preserves per-project tuning.

## User-perspective review (Codex, 2026-06-01)

A second Codex pass reviewed the *wired* harness from the user's lived perspective (not code
correctness — that was the Mode-3 pass). Verdict **adjust**. The findings and dispositions:

| # | impact | finding (what the user hits) | disposition |
|---|---|---|---|
| H1 | high | A-model hooks drift across projects; you forget which copy is patched | **addressed** — `# bootstrap-hooks vN` stamp + `/bootstrap-doctor` audit (this commit) |
| H2 | high | `NEXT.md` over-trusted: a git-fresh-but-semantically-stale handoff = polished false continuity | mitigated — FRESH remains explicitly git/shape scoped, and changed workflow/wiki/knowledge context files add a WARN instead of silently passing |
| H3 | high | Stop gate rewards "NEXT.md touched", not handoff quality (Goodhart) | mitigated — Stop and PreCompact now require a light NEXT handoff schema when NEXT was touched |
| H4 | high | default work-pattern `workflow/\|scripts/\|*.py` is Python-biased; JS/Rust/docs projects silently bypass | mitigated — templates now use broader mixed-repo defaults, and project-init carries stack-specific work-glob presets that must be applied to both Stop and PreCompact hooks |
| H5 | high | SessionStart FRESH banner every session → ignored wallpaper | mitigated — clean FRESH is one terse line; verbose output is reserved for stale/dirty/unverified or WARN cases |
| M6 | med | old-but-git-fresh handoff (time-based amnesia, human forgot intent) | pending — if `last_touched` old, inject "recap + confirm direction" nudge |
| M7 | med | runbook mixed with decision record | mostly-already — per-project `CLAUDE.md` IS the runbook; this spec is the record (reference, not cold-start reading) |
| M8 | med | `last_verified_commit` lifecycle under-specified | mitigated — spec/template define it as the latest verified unit commit and forbid root `NEXT.md` in `unit_paths` |
| M9 | med | "read only 1–2 pages" risks under-reading | pending — "start with 1–2; read more when callers/tests/schemas require" |
| M10 | med | opt-in ⇒ global policy overpromises (a project may be unprotected) | partly-addressed — `/bootstrap-doctor` shows each project's tier; protection boundary now visible |
| L11 | low | trial mode has no graduation story | pending — flip `TRIAL=0` after a smoke test / N clean sessions |
| L12 | low | dropping per-project `AGENTS.md` weakens direct Codex-in-project use | defer — user feeds Codex via prompt; cheap optional stub if ever needed |

Pending findings are **not yet applied** — each is a small UX/correctness adjustment awaiting a
go. Applying any hook change bumps the template version, at which point `/bootstrap-doctor`
flags the seeded copies (e.g. Hibiki) as OUTDATED — the drift-visibility loop working as intended.
