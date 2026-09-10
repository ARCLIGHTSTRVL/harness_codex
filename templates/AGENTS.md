# Project AGENTS.md Template

Drop this in a project root as `AGENTS.md`. It is the project-local
cold-start front door for direct Codex sessions. Keep it project-specific and
lean; global behavior stays in `~/.codex/AGENTS.md`.

Pattern: `dev-setup-codex/specs/project-bootstrap-continuity.md`.

---

# Project: <Name>

## Cold Start

Read complete but bounded context for the active unit: its goal and acceptance,
invariants, direct dependency contracts, current code references and evidence,
and settled decisions. Avoid unrelated history and redundant active-state copies.

1. `NEXT.md` - active work unit and handoff. Verify freshness before trusting it.
2. One-line indexes:
   - `wiki/index.md` for code mechanics and architecture
   - `knowledge/index.md` for research, findings, decisions
   - `workflow/README.md` or `workflow/status.md` for current phase
3. Then read the pages those files point to. Start with 1-2 pages, but treat that
   as an orientation heuristic rather than proof of completeness. Read the
   additional callers, tests, schemas, or contracts the unit actually requires.

## NEXT.md Freshness Check

Run before presenting `NEXT.md` as fact. Fail safe to stale.

1. `git merge-base --is-ancestor <last_verified_commit> HEAD`
   - Fails: rebase, squash, force-push, branch switch, or unknown base. Treat
     `NEXT.md` as suspect.
2. `git log <last_verified_commit>..HEAD -- <unit_paths>`
   - Non-empty: the active unit's files changed after the handoff. Treat that
     part as stale.
   - `unit_paths` must not include the root `NEXT.md`; handoff-only edits are
     metadata. If the NEXT template is the work, use `templates/NEXT.md`.
3. `git status --porcelain`
   - Dirty files under `unit_paths` without committed drift: WIP. This is
     expected mid-unit; at a cold start, inspect the diff before trusting the
     handoff's current-state claims, wiki pins, prior evidence, or worker results.
   - Dirty files outside `unit_paths`: review them as context before relying on
     a clean state, but they do not by themselves invalidate the active unit.
4. `last_touched` older than roughly 7 days is a hint only; recap and re-derive.
   Ask only if this exposes a genuinely new decision or scope change.
5. If `workflow/status.md`, `workflow/README.md`, `wiki/log.md`, `wiki/index.md`,
   `knowledge/log.md`, or `knowledge/index.md` changed after
   `last_verified_commit`, treat the freshness verdict as structurally valid but
   semantically worth a quick recap.

If any check trips, say why and re-derive from current committed and dirty source,
`workflow/status.md`, recent `wiki/log.md` / `knowledge/log.md`, and
`git log --oneline -20`. Ask the user only if that exposes a genuinely new
decision or scope change.

## Compaction Continuity

Codex may compact automatically. Treat a `SessionStart` freshness verdict
printed as `[freshness source=compact]` the same as a cold start: trust
`NEXT.md` only after the git freshness check passes, then read the pointed
context and compare it with current source. Checkpoint after substantive
decisions, verified phases, and integration, and before long pauses, major
edits, compaction, or a unit switch. Update `NEXT.md` for the single active unit
and keep paused-unit state in its plan or another workflow artifact. The exact
automatic compaction point is not under project control. If expected freshness
or compact verdicts never appear, run `/hooks` and confirm the project-local
hooks are trusted. No prompt or carry record erases history or guarantees zero
context rot.

For work likely to resume or for a substantive multi-phase unit, use
`workflow/plans/<canonical_id>.md` from `templates/plan-file.md`; do not invent
phases for simple work merely to satisfy a count.
Keep exactly one `<!-- handoff:begin -->` / `<!-- handoff:end -->` pair and
update its current phase, next action, and blockers before each pause. A seeded
SessionStart reader emits the saved Handoff of active plans, including after
compaction. It cannot recover unsaved conversation state or prove live delivery.
Do not put `workflow/plans/` in NEXT's `unit_paths`. At closure, route verified
results to knowledge, remove the completed plan, and subtract the unit from NEXT.
Keep NEXT within the default 60-line Stop budget; it is a pointer, not history.

## Goal

<One paragraph: what this project does, who uses it, what success looks like.>

## Stack

- Languages: <e.g., TypeScript, Python>
- Frameworks: <e.g., React, FastAPI>
- Build/Test: <e.g., npm test, pytest>
- Package manager: <npm | pnpm | uv | poetry>

## Architecture

```
<small component map or bullet tree>
```

## Where Things Live

| Concern | Path |
|---|---|
| Entry point | <src/main.ts> |
| Core logic | <src/> |
| Tests | <tests/> |
| Build artifacts | <dist/, release/> |
| Secrets/config | <.env, never committed> |

## Common Commands

```bash
<install>
<dev>
<test>
<build>
<release>
```

## Conventions

- Indent: <2 / 4 spaces / tabs>
- Naming: <camelCase / snake_case>
- Commit style: <conventional commits | freeform>
- Wiki language: <English | Korean>

## Key Constraints

- <runtime, platform, browser, schema, API, data, or deployment constraints>

## Forbidden

- <patterns, dependencies, generated files, or operations Codex must not use>

## Verification

- Required before completion: <commands>
- Manual smoke tests: <if automated tests do not cover behavior>
- Stop after the meaningful required checks pass unless a new edit, failure, or
  concrete unresolved concern justifies more. Do not require tests for a
  low-impact nonbehavioral edit.

## Local Knowledge

- `NEXT.md`: current single active work unit, not a backlog.
- `workflow/`: current phase tracking and broad status.
- `wiki/`: code mechanics, architecture, and source-pinned explanations.
- `knowledge/`: research, decisions, findings, and fragment consolidation.
- Source code is the behavioral source of truth; wiki is derived from it,
  knowledge preserves decision rationale, and observed execution is separate
  evidence. User acceptance defines the desired behavior.

## Project-Specific Notes

- <remote dev, OS-specific execution, long-running training, release signing, etc.>
