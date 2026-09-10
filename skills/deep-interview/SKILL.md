---
name: deep-interview
description: Socratic interview that scores its own understanding across weighted dimensions and gates on that self-assessment before committing to execution. Output is a clarified spec.md. Trigger words include "deep interview", "interview me", "ask me everything", "don't assume", "make sure you understand", "딥 인터뷰", "가정하지 마", "다 물어봐", "확실히 이해", "스펙 정리".
---

# deep-interview

Iteratively interview the user to drive a vague idea down to ≤ 20% ambiguity, then crystallize a spec.

## When to use

- User has a vague idea and wants thorough requirements gathering before execution
- User says "deep interview", "interview me", "ask me everything", "don't assume", "make sure you understand"
- User wants to avoid "that's not what I meant" outcomes from autonomous building
- Task is complex enough that jumping to code would waste cycles on scope discovery

## When NOT to use

- User has a detailed, specific request (file paths, function names, acceptance criteria)
- Quick fix or single-line change
- User says "just do it" or "skip the questions" — respect intent
- User already has a PRD or plan file

## Execution policy

- Ask **ONE question at a time** — never batch multiple
- Target the WEAKEST clarity dimension with each question
- Gather codebase facts (read/grep) BEFORE asking the user about them
- Score ambiguity after every answer; display the score transparently
- Do not declare done until ambiguity ≤ 0.2 (or user opts to early-exit with warning)
- Challenge agents activate at specific round thresholds

## Phases

### Phase 1 — Initialize

1. Parse the user's idea from arguments.
2. Detect brownfield vs greenfield: is there existing source code in cwd that this idea touches?
3. For brownfield: scan relevant codebase areas first (Read/Grep/Glob), keep findings as `codebase_context`.
4. Announce:
   > Starting deep interview. I'll ask targeted questions to understand your idea thoroughly before building. After each answer I'll show your clarity score. We proceed to execution once ambiguity drops below 20%.
   >
   > Idea: "{idea}"
   > Type: {greenfield|brownfield}
   > Current ambiguity: 100%

### Phase 2 — Interview loop

Repeat until `ambiguity ≤ 0.2` or user exits early:

**2a. Generate next question**
- Identify the dimension with the lowest clarity score
- Generate ONE question targeting that dimension
- Question should expose ASSUMPTIONS, not gather feature lists

Question styles:
| Dimension | Style | Example |
|---|---|---|
| Goal | "What exactly happens when…?" | "When you say 'manage tasks', what specific action does a user take first?" |
| Constraints | "What are the boundaries?" | "Should this work offline, or is internet connectivity assumed?" |
| Success Criteria | "How do we know it works?" | "If I showed you the finished product, what would make you say 'yes, that's it'?" |
| Context (brownfield) | "How does this fit?" | "The existing auth uses JWT in src/auth/. Extend that or add a separate flow?" |

**2b. Ask**
Present as:
```
Round {n} | Targeting: {weakest_dimension} | Ambiguity: {score}%

{question}
```

**2c. Score ambiguity** (after answer)

> **The arithmetic below is real; the inputs are not measurements.** Each dimension's
> 0.0–1.0 value is the model's own judgement of its own understanding, so the weighted
> total is a self-assessment with decimals attached — and a model that has misunderstood
> the problem will score its understanding of it highly. Treat the number as a structured
> prompt to keep asking, never as evidence that enough was asked. Its real work is
> forcing per-dimension attention and naming the weakest one; the threshold is a
> stopping convention, not a proof.

Score each dimension 0.0–1.0:
- Goal Clarity — primary objective unambiguous, statable in one sentence
- Constraint Clarity — boundaries, limitations, non-goals clear
- Success Criteria — could you write a test for it; concrete acceptance criteria
- Context Clarity (brownfield only) — existing system understood enough to modify safely

Calculate ambiguity:
- Greenfield: `ambiguity = 1 - (goal × 0.40 + constraints × 0.30 + criteria × 0.30)`
- Brownfield: `ambiguity = 1 - (goal × 0.35 + constraints × 0.25 + criteria × 0.25 + context × 0.15)`

**2d. Report progress**
```
Round {n} complete.

| Dimension | Score | Weight | Weighted | Gap |
|---|---|---|---|---|
| Goal | {s} | {w} | {s*w} | {gap or "Clear"} |
| Constraints | {s} | {w} | {s*w} | {gap or "Clear"} |
| Success Criteria | {s} | {w} | {s*w} | {gap or "Clear"} |
| Context (brownfield) | {s} | {w} | {s*w} | {gap or "Clear"} |
| **Ambiguity** | | | **{score}%** | |
```

**2e. Check round limits**
- Round 3+: allow early exit if user says "enough", "let's go", "build it"
- Round 10: soft warning — "We're at 10 rounds. Current ambiguity: {score}%. Continue or proceed?"
- Round 20: hard cap — proceed with current ambiguity, note the risk

### Phase 3 — Challenge modes

Activate ONCE each at round thresholds, then return to normal Socratic questioning:

| Round | Mode | Effect |
|---|---|---|
| 4+ | Contrarian | "What if the opposite were true?" — challenge a core assumption |
| 6+ | Simplifier | "What's the simplest version that would still be valuable?" — probe for removable complexity |
| 8+ (if ambiguity > 0.3) | Ontologist | "What IS this, really?" — find the essence when symptoms keep recurring |

Track which modes have been used.

### Phase 4 — Crystallize spec

When ambiguity ≤ threshold (or hard cap / early exit), write `specs/deep-interview-{slug}.md`:

```markdown
# Deep Interview Spec: {title}

## Metadata
- Rounds: {count}
- Final Ambiguity: {score}%
- Type: greenfield | brownfield
- Status: PASSED | EARLY_EXIT

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| ... | ... | ... | ... |

## Goal
{crystal-clear single-sentence goal}

## Constraints
- ...

## Non-Goals
- ...

## Acceptance Criteria
- [ ] testable criterion 1
- [ ] testable criterion 2
- [ ] ...

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|---|---|---|
| ... | ... | ... |

## Technical Context
{brownfield: relevant codebase findings}
{greenfield: technology choices and constraints}

## Interview Transcript
<details><summary>Full Q&A ({n} rounds)</summary>

### Round 1
**Q:** ...
**A:** ...
**Ambiguity:** {score}%

...
</details>
```

### Phase 5 — Hand off

After spec is written, suggest next step (do NOT auto-execute):
- "Spec is at `specs/deep-interview-{slug}.md`. Ready to start implementation, or want me to refine further?"

The user decides whether to proceed, refine, or hand to another tool.

## Tool usage

- `AskUserQuestion` for each interview question (clickable options + free text)
- `Read`/`Grep`/`Glob` for brownfield codebase exploration BEFORE asking the user
- `Write` to save the final spec

## Stop conditions

- Hard cap at 20 rounds: proceed, note risk
- Soft warning at 10 rounds: offer continue or proceed
- Early exit (round 3+): allow with warning if ambiguity > threshold
- "stop", "cancel", "abort": stop immediately
- All dimensions ≥ 0.9: skip to spec generation
- Ambiguity stalls (same ±0.05 for 3 rounds): activate Ontologist mode to reframe

## Ambiguity score interpretation

| Range | Meaning | Action |
|---|---|---|
| 0.0–0.1 | Crystal clear | Proceed |
| 0.1–0.2 | Clear enough | Proceed (default threshold) |
| 0.2–0.4 | Some gaps | Continue interviewing |
| 0.4–0.6 | Significant gaps | Focus on weakest dimensions |
| 0.6–0.8 | Very unclear | May need reframing (Ontologist) |
| 0.8–1.0 | Almost nothing known | Early stages, keep going |

## Examples

Good:
- Targeting weakest dimension: scores Goal=0.9, Constraints=0.4, Criteria=0.7 → next question is about constraints
- Gathering codebase facts first: read/grep for auth, then ask informed question instead of "what database does your project use?"
- Contrarian mode: "You said 10K concurrent users. What if it only needed to handle 100? Is the 10K measured or assumed?"
- Early exit with warning: show remaining gaps, ask user to confirm

Bad:
- Batching multiple questions in one round
- Asking about codebase facts the code already reveals
- Proceeding despite high ambiguity (e.g., 45% with no warning)

## Why this exists

Standalone Socratic interview skill; the gate is a weighted SELF-assessment, not a measurement. No plugin dependencies — uses Read/Grep/Glob directly. Outputs a spec; does not auto-handoff to execution.
