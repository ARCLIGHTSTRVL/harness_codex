# Freshness Detection Spine — long-term maintenance without vigilance burden

**Status: SPEC LOCKED. ① ② ③ ④ shipped 2026-06-04 (both machines) — but "shipped" ≠ "all invariants held": the 2026-06-10 signal-layer audit found dead hooks + a fail-open verdict (fixed same day, see `knowledge/comparisons/harness-signal-layer-fix.md`), and the 2026-06-10 cold eval found invariant 2/6's execution proof unimplemented until the `~/.claude/.last-health` heartbeat (machine-global, home dir) landed that day. Hook-side coverage is the cheap tier only; deep checks are `/doctor`'s by design.**
- 2026-06-29 direct-Codex port: the Claude global SessionStart hook below is
  preserved as design history, not installed by this repo. Current automatic
  Codex context injection is project-local: `.codex/hooks.json` runs
  `freshness-inject.sh` at SessionStart and `compact-handoff-gate.sh` at
  PreCompact. `scripts/project-health.py` remains the shared cheap checker used
  by `/doctor`, `setup-check` selftest, manual runs, and any explicitly wired
  hook.
- 2026-06-04: **Phase 1 BUILT** — global project-health SessionStart hook (`scripts/project-health.py`
  detector + `scripts/install-health-hook.py` atomic merge + installer step [5] + setup-check liveness).
  Invariants 1-8 implemented; two Codex Mode-3 reviews applied; real `~/.claude/settings.json` mutation verified.
- 2026-06-04: **② BUILT** — consolidated `/doctor` (`scripts/doctor.py`): runs NEXT + bootstrap-hooks +
  wiki-lint + kb-lint for the current project, records `<project>/.claude/.last-doctor` so the hook surfaces
  doctor age/overdue. Fail-safe (uncertain/could-not-run -> ATTENTION, never "all clear"); per-check isolation;
  KR mirror deferred to `/knowledge-mirror`. project-health filters `.claude/.last-doctor` etc. from the NEXT
  dirty-check (rename/copy guarded). Codex Mode-3 applied (fail-safe attention, tooling-state filter, isolation).
- 2026-06-04: **③ BUILT** — knowledge-mirror exclusion. Vault-side `<kr_dir>/_mirror-ignore.txt`
  (one en_source per line + `# reason`) -> excluded EN pages report `IGNORED` not `MISSING`; a dangling
  entry surfaces as `IGNORE-STALE` (never a silent suppression). Vault-side (not EN frontmatter) so it
  works when the EN source is read-only -- the concrete driver: project_hibiki's dogfood-findings (KB-system
  meta, lives in the harness spec) was a permanent MISSING false-positive; now IGNORED with reason.
- 2026-06-04: **④ BUILT** — cadence surfaced, not memorized. `project-health` flags `doctor Nd ago (overdue)`
  when > 7 days; the global CLAUDE.md `<project_bootstrap>` block carries the session-start health-line action
  rules (NEXT stale → resolve; doctor overdue → /doctor), the cadence (session=health / weekly=/doctor /
  milestone=full audit), and the liveness-absence guard (no health line in a managed project ⇒ hook unwired,
  not "all fresh" ⇒ /setup-check). **Spine complete.**

## Codex port note

This spec preserves the Claude-era design history. In this direct-Codex repo,
the current operational surface is:

- global policy: `codex/AGENTS.md` -> `~/.codex/AGENTS.md`
- project hooks: `.codex/hooks.json` plus project-owned `.codex/hooks/*`
  (`command` for POSIX, `commandWindows` for Windows)
- cheap project detector: `scripts/project-health.py` (shared checker; not
  installed as a global Codex hook by this repo)
- deep project detector: `scripts/doctor.py`
- install drift detector: `scripts/setup-check.py`

Historical references to `~/.claude`, `CLAUDE.md`, Claude Code hook wiring, and
global project-health SessionStart installation below are provenance unless a
Codex port note says otherwise.

**Relation:** extends `project-bootstrap-continuity.md`. The cold-start NEXT.md freshness hook
specified there is a *subset* of the global health detector specified here.

## Problem

The harness has rich per-project knowledge layers (wiki/ = how code works; knowledge/ =
research record; NEXT.md = active handoff; workflow/; memory/; + a Korean Obsidian read-mirror
of knowledge/). The source-of-truth split is sound (in-repo litmus). But **maintenance leans on
tier-B**, and that rots over months and many projects.

The 3 automation tiers (how anything fires):
- **A. machine-automatic** — loads/fires with no human or agent action (Claude Code runtime).
- **B. policy-nudged (agent-driven)** — CLAUDE.md says "when X do Y"; relies on the AGENT
  remembering/following it. NOT machine-enforced.
- **C. manual** — only on user command or explicit agent invocation.

Today the knowledge→Obsidian chain is almost entirely B or C. Detection tools exist (wiki-lint,
kb-lint, knowledge-mirror status, bootstrap-doctor, setup-check) but **nothing schedules them →
silent rot until someone happens to run them.** Tier-B is a *suggestion layer, not a control
plane*: across context resets and sessions, "orient at session start / refresh after code change
/ offer write-back" fail silently.

## The bar (what "good" means here)

Crystallized with the user: **the user is a reliable operator** — "if you surface it, I will not
ignore it; I always act." Given that, **the entire residual risk collapses onto DETECTOR
ACCURACY.** The freshness system's reliability == the detector's reliability on two axes:

- **false negative** = a real staleness the detector never surfaces. **WORST** — invisible, the
  user only acts on what is surfaced, so an unsurfaced staleness rots forever.
- **false positive** = says stale/wrong when not. Noise; erodes trust. Bad, but the user sees and
  dismisses it.

**False negatives are far worse than false positives.** The detector must therefore bias toward
over-reporting: when unsure, say stale/unverified, never fresh.

**Goal:** offload the freshness *vigilance* burden (remembering to check; knowing what/when is
stale) entirely to a trustworthy detector. The user's only remaining job is to ACT on accurate
surfaced items — and on that, given a reliable operator, there is no place left for the user to
make a mistake.

**Honest scope (the offload is partial):** offloadable = **structural** freshness within declared
coverage. NOT offloadable = **semantic** correctness (is the content actually right/current vs
reality). See boundary section.

## Decision

Build a small **tier-A detection spine**. Move detection *off agent memory* (tier-B, unreliable)
*onto deterministic, unit-tested scripts/hooks* (tier-A). **Trust comes from tested code +
observable execution, never from agent recall.** Do not rely on tier-B for correctness; reclassify
anything correctness-relevant as either tier-A detection or an explicit manual ritual.

Detection is automatic; **remediation stays manual** (translation, content edits, judgment). The
spine surfaces; it never auto-fixes content (auto-fixing semantic content would violate the
`knowledge_fidelity` principle).

## Detector invariants (acceptance criteria — ALL must hold)

1. **No silent skip [keystone].** In global-hook mode, every candidate repo ends in exactly ONE
   visible state: `CHECKED` / `UNVERIFIED` / `NOT A MANAGED PROJECT` / `FAILED`. Silence is valid
   ONLY for unmanaged dirs (no markers — the global hook fires in every dir and must not spam
   them); a managed dir ALWAYS emits a health line, and `/doctor` prints NOT MANAGED explicitly.
   Direct-Codex port: because this repo does not install a global health hook, this invariant
   applies when `project-health.py` is run manually or explicitly wired by the user.
2. **Liveness sentinel.** Claude-era global hook mode: every managed session prints a health line
   ALWAYS — even "0 issues" / "skipped" / "failed". Its absence must be conspicuous. A hook cannot
   prove its own non-execution from inside, so `setup-check` (or bootstrap) separately verifies the
   global hook is installed, executable, current, and *recently observed to have run*. (Implemented
   2026-06-10: the hook writes the machine-global `~/.claude/.last-health` heartbeat on every real
   run — its sole write, see invariant 8; home dir, NEVER the project worktree, so no managed repo
   is dirtied; `--selftest` deliberately does not write it, or setup-check's own probe would
   refresh it and the recency check would be vacuous. Before that date this clause was aspiration,
   not implementation.) Direct-Codex port: `setup-check` verifies `project-health.py --selftest`
   rather than hook recency; project-local `.codex/hooks.json` provides automatic NEXT freshness
   injection for projects that opt in.
3. **Fail-safe, including discovery.** Uncertainty → UNVERIFIED/stale, never fresh. Applies to:
   unknown project, malformed metadata, unsupported pin type, timeout, missing dependency,
   permission error.
4. **FRESH is earned AND scoped.** No blind sha stamps; FRESH only when actually verified, and
   labeled "FRESH for byte/pin check," never globally fresh.
5. **Coverage explicit.** The detector states what it checked AND what it skipped / could not
   support — so the user knows the boundary of the green signal.
6. **Observable execution + bounded failure.** A durable/visible record that it ran: exit status,
   timestamp, repo root, checker versions, timeout/error state.
7. **Raw machine output, minimal agent paraphrase.** The health block reaches the user as
   machine-generated text. The agent must NOT re-summarize it — agent paraphrase can reintroduce
   the wrong/missing-info failure this spine exists to remove.
8. **Detection automatic when wired, remediation manual.** The spine detects + surfaces; fixing
   stays with agent+user. Never auto-fix content. (Amended 2026-06-10: the detector's ONE
   permitted write in hook mode is its own liveness heartbeat `~/.claude/.last-health` —
   machine-global in the home dir, never a project worktree — because invariant 2's execution
   proof is impossible without it.) Direct-Codex port: `project-health.py` writes
   `~/.codex/.last-health` only when the checker actually runs; it is not currently a global-hook
   liveness guarantee.

## Structural vs semantic boundary (terminology discipline)

**Offloadable — structural signals (machine-trustworthy):** EN↔KR sha match; NEXT↔git state; wiki
pins falling in changed source regions + broken pins / moved-or-renamed symbols / deleted targets /
changed dependency+config files; broken links / orphans; hook version drift.

**NOT offloadable — semantic:** whether the content is correct/current vs reality. Specifically:
- `EN↔KR sha match` means "KR corresponds to the current EN hash," NOT "KR is correct." If EN is
  stale vs reality, KR faithfully mirrors stale content.
- `wiki pins in unchanged region` does NOT guarantee prose correctness — only that the pinned
  anchor saw no relevant structural source change. Behavior can change outside the pinned range.
- `knowledge sha-pinned raw` proves provenance stability, not truth / completeness / currency.

**RULE:** health output NEVER says "X is fresh." It says **"no structural staleness detected within
checked coverage."** Green health must not imply semantic correctness. The user's offloaded burden
is the structural "is it in sync" part; "is the content correct" stays with agent+user at
remediation time.

## NEXT verdict contract (shared truth table)

Two implementations — the per-project hook (`templates/hooks/freshness-inject.sh`) and the shared
checker (`scripts/project-health.py`) — MUST give the same verdict class. Frontmatter keys:
`last_verified_commit:` primary, `last_verified:` fallback (both sides). "Real dirt" =
`git status --porcelain` minus our tooling-state files (`.codex/.last-doctor`,
`.last-health`, `.stop-warned-*`, `.compact-warned-*`; rename/copy records are never
filtered out). Historical Claude-era records used `.claude/*`; the direct-Codex port uses
`.codex/*`. `unit_paths` describes the work unit, not handoff metadata; root
`NEXT.md` in `unit_paths` is UNVERIFIED because a handoff-only commit would
self-invalidate.

| condition | verdict |
|---|---|
| valid base SHA, ancestor of HEAD; unit_paths declared, all exist, no commits touching them since base, no real dirt on them | FRESH (real dirt elsewhere or changed workflow/wiki/knowledge context files ⇒ verdict unchanged + WARN suffix) |
| any declared unit_path missing from the working tree | STALE |
| real dirt touching a unit_path, with ancestry/committed checks otherwise fresh | WIP (inspect current diff; not committed staleness) |
| commits touched unit_paths since base | STALE (hook wording: PARTIALLY STALE) |
| base SHA not an ancestor of HEAD | STALE |
| no unit_paths declared | UNVERIFIED |
| root NEXT.md appears in unit_paths, required handoff fields/sections missing, or seeded placeholders remain | UNVERIFIED |
| base SHA invalid / unknown to git | UNVERIFIED |
| no base key in frontmatter / any git error | UNVERIFIED |

## Build set

1. **Claude-era global SessionStart project-health hook / direct-Codex checker port**
   (`~/.claude/settings.json`, NOT per-project seed → uniform, no per-project drift; distinct
   from the per-project bootstrap hooks):
   - Direct-Codex port note: this repo does not install a global Codex SessionStart health
     hook. `scripts/project-health.py` remains the cheap line checker reused by `/doctor`,
     `setup-check` selftest, manual runs, and any explicitly wired user hook. Codex automatic
     context injection for project bootstrap is the project-local hook in item 2a.
   - Marker detection: `.git` + any one of `wiki/SCHEMA.md` / `knowledge/SCHEMA.md` / `NEXT.md` =
     candidate project. Incomplete markers → `UNVERIFIED: missing markers`, never skip. No markers →
     `NOT A MANAGED PROJECT`.
   - Managed project without a `NEXT.md`: the line carries an explicit `NEXT none` segment —
     absence is visible, never a silently omitted segment (2026-06-10 cold-eval fix; a missing
     segment reads as "nothing to check", a false-negative shape).
   - Read-only. Emits the always-on health line (invariants 1/2/5/6).
   - Checks (hook-side = the cheap tier ONLY): NEXT git-truth freshness (defined narrowly +
     pessimistically — referenced base SHA is ancestor of HEAD AND no uncommitted edits to NEXT's
     unit_paths; uncommitted edits on those paths are NOT fresh just because HEAD matches); bootstrap-hook
     version drift + execution proof; "doctor overdue" (days since last successful /doctor); and
     the liveness heartbeat write. The deep counts — wiki structural staleness, knowledge lint,
     KR-mirror stale/missing/orphan/dup — are `/doctor`'s job; the hook only surfaces "doctor
     overdue", it does NOT run them (truth-down 2026-06-10; `project-health.py`'s docstring is
     authoritative for hook-side coverage).
   - HARD-WARN / gate ONLY on severe NEXT staleness (the resume-correctness invariant). Everything
     else = surface-not-block, but as **unambiguous action items** (top offenders + an expand
     command), never bare counts.
2. **Consolidated `/doctor`** — runs the project-scoped deep checks in one prioritized report:
   NEXT git-truth, bootstrap-hook version, wiki-lint, kb-lint, fragment consolidation debt.
   setup-check / bootstrap-doctor / knowledge-mirror are POINTED TO, not run (harness-wide and
   interactive surfaces stay separate. Records a last-run timestamp per managed
   project on every run, including attention results. The stamp measures cadence;
   exit status and individual findings carry cleanliness. Context-budget checks
   delegate to the project's engine when its contracts file exists.
2a. **Codex automatic compaction continuity** — project hooks are seeded through
   `.codex/hooks.json`. `SessionStart` with source `compact` re-runs the NEXT freshness
   verdict after compaction. `PreCompact` runs a one-nudge handoff gate so automatic
   compaction does not silently summarize away an unrecorded active unit. The template
   must carry both POSIX `command` and Windows `commandWindows` entries so the hook is not
   disabled by shell quoting differences. `commandWindows` must preserve `$LASTEXITCODE`
   so Stop's `exit 2` remains a blocking signal. The SessionStart verdict includes the
   hook source in its prefix (for example, `[freshness source=compact]`) so a compact
   re-entry is visible in the model context. Because these are project-local non-managed
   hooks, `project-init` must tell the user to review/trust them with `/hooks` after
   merging and tuning the final definitions; copied hook files alone are not proof
   that the protection is active.
3. **Cadence (surfaced, not memorized).** Claude-era global hook mode: session = always-on health
   line (auto); the hook surfaces "doctor overdue" so the weekly / after-major `/doctor` is
   *prompted, not remembered*; milestone = full lint + audit + NEXT check. Direct-Codex port:
   the automatic part is project-local NEXT freshness / PreCompact continuity; broader
   project-health cadence is manual unless the user explicitly wires a global hook.
4. **knowledge-mirror exclusion.** Vault-side `<kr_dir>/_mirror-ignore.txt` (one `en_source` per
   line + `# reason`) → `knowledge-mirror status` reports `IGNORED` (not `MISSING`); a dangling
   entry surfaces as `IGNORE-STALE`, never a silent suppression. Vault-side rather than EN
   frontmatter `mirror: false` (the first-cut design) so it works when the EN source is read-only.
   `/doctor` lists all exclusions + count — an accidental/stale exclusion must be auditable, never
   silent (else exclusion becomes a new false-negative source).

## Decisions & pushbacks recorded

- **Non-NEXT staleness is surface-not-block.** The user is a reliable operator who acts on surfaced
  items; hard-blocking on cosmetic staleness = "guilt-driven clutter" (warned against in the
  maintainability review). Only NEXT (resume correctness) hard-gates. *(Pushback against the
  reviewer's "make it an unmistakable warning even if not a block" → the "unambiguous action item,
  not bare count" part is accepted; escalation to hard-block is rejected.)*
- **workflow/status.md demote is a SEPARATE cleanup**, decoupled from this freshness build — it does
  not improve detector accuracy. Use status.md only when a project has genuinely multiple parallel
  threads; else NEXT.md suffices.

## Status & provenance

- SPEC LOCKED 2026-06-04. Build COMPLETE — ① ② ③ ④ all shipped 2026-06-04 (see header log).
- Derived from a multi-turn design + **two independent Codex Mode-3 reviews**:
  1. *Maintainability review* → verdict: "not a stable long-term equilibrium; rich layers + thin
     tier-B enforcement rots; needs a small tier-A spine that detects staleness and makes the next
     action obvious." Strongest part = in-repo litmus; weakest = freshness/drift detection is
     agent-remembered.
  2. *Intent-match review* → verdict: "intent match PARTIAL until false-negative holes closed."
     Produced the keystone **No silent skip** invariant + the **liveness sentinel** + **doctor-overdue
     surfacing** + the **raw-output / no-agent-paraphrase** rule + the **terminology discipline**
     (never unqualified "fresh"). All accepted; one pushback (surface-not-block for non-NEXT).
- **Claude-era build order when resumed:** global health hook + sentinel → consolidated `/doctor`
  + overdue tracking → exclusion-with-reason → cadence doc. Each tier-A piece must be unit-tested
  per the invariants (as knowledge-mirror's FRESH/STALE/MISSING/ORPHAN/DUP branches were). Wire
  pointers into CLAUDE.md / skills ONLY after the pieces are built — do not front-load context for
  an unbuilt spine. Direct-Codex port keeps the tested checker and doctor path, while automatic
  context injection is project-local via `.codex/hooks.json`.
