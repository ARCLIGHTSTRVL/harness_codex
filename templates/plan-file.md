---
# workflow/plans/<canonical_id>.md -- active-unit plan (plan_schema: 1)
#
# Lifecycle: created when a substantive multi-phase unit or likely resumption
# needs durable working state. Do not split simple work into artificial phases;
# smaller units keep their plan in chat. DELETED at unit close after verified results
# route to the project's knowledge layer (closure/synthesis page) + one PLAN
# completion line, with NEXT SUBTRACTING the unit's line (2026-09-01 flip of the
# 2026-08-18 absorb-into-NEXT decision: absorb-only rules made NEXT grow
# monotonically -- this file stays working state, and keeping it would be a
# third copy of unit history, the known two-spellings drift family).
# NEVER add workflow/plans/ to NEXT unit_paths -- plan edits are the unit
# progressing, not an event that should stale NEXT.
unit: <canonical_id from knowledge/_fragments/units.yml>
created: <YYYY-MM-DD>
status: active   # active | paused | abandoned (never a durable "done" -- done plans are
                 # absorbed and deleted). Only `active` is carried across compaction.
                 # Use one of these three: a value outside the set is not read as
                 # "not active", it is reported as a status nobody could establish.
plan_schema: 1
---

# <unit> — plan

## Goal

<ONE verifiable sentence — the check that decides "done", not a wish.>

## Phases

<!-- Each real phase: concrete steps (exact paths, real commands — placeholders
     banned), one `verify:` line naming a MEANINGFUL RUNNABLE check, and `result:` folded
     back AFTER that verify passes — write what actually happened, surprises
     included, never before the check runs. A phase with no runnable verify is
     not a phase; split or merge until it has one.
     Two bounded exceptions:
     - A phase whose shape depends on an EARLIER phase's outcome states that
       dependency explicitly and is fully concretized when it becomes active —
       the placeholder ban binds ACTIVE phases; an honest stated dependency is
       not a placeholder.
     - The FINAL (close) phase cannot fold its own `result:` back — closing
       deletes this file — so its result is recorded in the knowledge closure + deltas instead,
       and the deletion is verified from OUTSIDE the file (git status). -->

### P1 — <name>
- <step with exact file paths / commands>
- verify: <runnable check>
- result: <blank until the verify passes>

### P2 — <name>
- <steps>
- verify: <check>
- result:

## Decisions

<!-- One line each, dated. The full reasoning goes to a knowledge fragment delta
     the moment it crystallizes (/knowledge-fragment) — this list is the index,
     never the record. -->

## Risks / open

<!-- The open half: risks, rejections-with-why, open questions discovered
     mid-unit. Record real items and their disposition. This section may be empty
     when no unresolved item remains; do not invent a risk to fill it. -->

## Handoff

<!-- Overwrite after substantive decisions, verified phases, or integration and
     at EVERY pause (session end, compaction near, unit switch):
     current phase · next single action · blockers. A cold session must resume
     from this section plus the phase results alone — write for a reader with
     zero conversation memory.

     The two marker lines below are what the SessionStart plan-handoff.py reader searches for.
     Keep them around the content when you overwrite it: they are the whole
     selector, replacing a Markdown parse that took three review rounds and
     was still wrong. Exactly ONE pair per file — a second pair makes the
     file ambiguous and the hook injects a named verdict instead of your
     state, deliberately, because guessing which pair is real is how the
     WRONG state gets carried. The match is exact after trailing whitespace,
     so an INDENTED copy does not match: indent them by two spaces if a plan
     ever needs to show the markers as an example. -->

<!-- handoff:begin -->
Current phase · next single action · blockers.
<!-- handoff:end -->
