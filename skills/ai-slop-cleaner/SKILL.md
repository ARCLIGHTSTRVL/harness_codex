---
name: ai-slop-cleaner
description: Clean AI-generated code slop with a deletion-first, behavior-preserving workflow and scoped verification. Trigger words include "deslop", "anti-slop", "AI slop", "cleanup the slop", "remove dead code", "데드 코드 제거", "AI 슬롭 정리", "AI 코드 정리".
---

# ai-slop-cleaner

Systematically clean AI-generated bloat (duplicate helpers, dead branches, wrapper layers, weak tests, boundary leaks) without changing behavior.

## When to use

- User explicitly says "deslop", "anti-slop", or "AI slop"
- Cleanup or refactor for code that feels bloated, repetitive, or overly abstract
- User calls out duplicate code, dead code, wrapper layers, boundary violations, or weak regression coverage
- Goal is simplification and deletion, not new features

## When NOT to use

- New feature build (just implement directly)
- Broad architecture redesign (use planning tools)
- Generic refactor with no cleanup intent (clarify scope first)
- Behavior is unclear and no reliable source or execution anchor can be established (investigate before editing)

## Execution policy

- Preserve behavior unless user explicitly asks to change it
- Lock behavior with regression tests first when the cleanup could change behavior and a meaningful test is practical. Do not add tests for a low-impact nonbehavioral deletion.
- Write a cleanup plan when the work is substantive or likely to resume; keep a small single-pass cleanup in the working plan/chat.
- Prefer deletion over addition
- Reuse existing utilities before introducing anything new
- Avoid new dependencies unless explicitly requested
- Keep diffs small, reversible, smell-focused
- Writer/reviewer separation: don't author and self-approve in the same pass

## Steps

### 1. Lock behavior

- Identify current behavior and its source or execution anchors. Add or
  strengthen regression tests before cleanup when the change could affect
  behavior and the test would distinguish a regression.
- When a new test is not meaningful, record the direct verification instead.

### 2. Plan the cleanup at the required scale

- List the targeted smells and likely files
- Sequence passes from lowest-risk deletion to higher-risk consolidation

### 3. Categorize the slop

- Duplicate code
- Dead / unused code
- Needless abstraction / wrapper layers
- Boundary violations / misplaced responsibilities
- Missing or weak tests

### 4. Execute one smell-focused pass at a time

- **Pass 1 — Dead code deletion**: unused branches, helpers, exports, stale comments
- **Pass 2 — Duplicate removal**: consolidate repeated logic into existing patterns
- **Pass 3 — Naming + error handling**: tighten naming, trim noisy plumbing, normalize inconsistencies
- **Pass 4 — Test reinforcement**: fill regression gaps revealed by cleanup

### 5. Run scoped quality gates

Run the meaningful lint, typecheck, unit/integration, static, security, or native/runtime checks required by the changed behavior. Stop after they pass unless a new edit, failure, or concrete unresolved concern justifies more. If a gate fails, fix the underlying issue or reverse only the cleanup changes you own with a safe patch; never reset or overwrite unrelated user work.

### 6. Optional review pass (`--review`)

A separate reviewer-only pass that does NOT edit. Inspects the cleanup result for:

- Leftover dead code or unused exports
- Duplicate logic not consolidated
- Needless wrappers still blurring boundaries
- Missing tests / weak verification
- Cleanup that quietly changed behavior

If issues are found, hand them to a follow-up writer pass; the reviewer does not edit. When delegation is authorized and a reviewer role is configured and available, use it without inventing a role or model. Verify its result against current code before accepting it, and keep one writer per shared target.

## Final report

Always end with:

- Changed files
- Simplifications made
- Behavior anchors and any tests added
- Verification run (lint/typecheck/tests)
- Remaining risks or slop intentionally left for later

## Examples

Good:
- "deslop this module — too many wrappers, duplicate helpers, dead code"
- "cleanup AI slop in src/auth: remove dead code and tighten boundaries"

Bad (different intent — don't use this skill):
- "refactor auth to support SSO" (feature work)
- "clean up formatting" (formatting-only doesn't need full workflow)

## Why this exists

Generic deslop workflow with no plugin dependencies.
