# Knowledge lifecycle

The agent captures a decision, finding, rejected alternative, risk or open question
when it becomes consequential. That duty is in the installed global policy; invoking
a skill manually is not the only trigger. It applies to projects with knowledge/_fragments/.
The project SCHEMA governs the record format and domain vocabulary.

## Initialize

Use scripts/init-knowledge.py with the project path. Preview is the default; --apply
creates only missing files/directories. --hooks adds missing Stop, PreCompact and
SessionStart templates. If a configuration already exists, inspect/merge it explicitly.
Review exact definitions in the host trust UI. The templates require a Git project;
Git initialization and commits remain project-owner decisions.

Use project-init for the full project-specific AGENTS/wiki conventions. The initializer
does not silently choose models, commit files or alter every project on the machine.
The source ZIP also ships an empty knowledge/_fragments/units.yml seed.

## Capture and distill

1. Register a canonical unit in knowledge/_fragments/units.yml. Obtain a fresh delta ID
   with deltas-for.py --next-id SESSION_ID, including after an earlier fragment was archived.
2. Write the delta using knowledge-fragment/SKILL.md's schema. Keep evidence and any
   alternatives or uncertainty that actually arose; do not invent risks or rejected
   options to fill a template. Evidence is needed to mark it accepted; capture precedes implementation.
3. At a unit boundary run consolidate.py KNOWLEDGE UNIT --draft. This preserves original
   fragments and writes a review draft. Applying an untouched DRAFT is refused.
4. The agent distills the draft into a durable page, preserving reasoning and risks and
   verifying quantitative claims from sources. Follow the task's review/approval authority.
5. Run --apply. The tool writes or updates the target's provenance, changes only selected
   delta statuses and archives fully disposed fragments. It retains source evidence.
6. Update the knowledge index/log and run kb-lint. Route code evidence to wiki-pages-for,
   reconcile affected wiki claims against source, and run wiki-lint. Doctor reports
   broken links, malformed records and outstanding consolidation debt; it does not
   independently judge the semantic quality of distilled prose.

## Preserve and resume

Write active decisions, risks and next steps into NEXT.md and the active plan's Handoff.
Include the unit's acceptance criteria, source basis, relevant dependency contracts and
verified results. When code, requirements or dependency contracts change, recheck affected
wiki claims, prior evidence and delegate reports before reuse. A small starting set of
pages is an orientation aid; it does not replace the full context needed by the unit.
PreCompact records a bounded copy of this saved handoff. SessionStart can emit it back
to the model after compaction. Stop/project gates check handoff freshness/shape.
The durable knowledge pages and archived original deltas remain in the project.
None of these hooks reconstructs unrecorded conversation or performs semantic distillation.

## Verification boundary

tests/test_distribution.py uses a fresh extracted ZIP and temporary profile/project.
It records a decision with a rejected alternative and risk, verifies draft application
is refused before distillation, applies an authored reviewed result, checks archived
evidence and the next delta ID, runs kb-lint and emits saved compact carry through the
actual hook adapters. This validates deterministic plumbing. A test-authored draft is
not a measurement of live model judgment; adapter emission is not proof of host dispatch.
