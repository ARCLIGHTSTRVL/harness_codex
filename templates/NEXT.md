---
last_verified_commit: <git-sha>
last_touched: <YYYY-MM-DD>
writer: <codex|human|other>
unit_paths: <space-separated repo-relative paths touched by this unit>
---

# NEXT

This file is the single active handoff. It is not a backlog.
Keep it within 60 lines. Phase detail belongs in `workflow/plans/`; closed-unit
results belong in knowledge. Remove completed unit text rather than appending
history. Do not list `workflow/plans/` in `unit_paths`.

`last_verified_commit` is the latest commit whose unit state and pointers were
verified. Exclude the root `NEXT.md` from `unit_paths`; handoff-only commits
after `last_verified_commit` should not make the unit stale by themselves. If
the NEXT template itself is the work, use `templates/NEXT.md` as the unit path.

## Active Unit

Goal: <one concrete outcome>

Current state:
- <what is already true>
- <what remains uncertain>

Blocker:
- <none | exact blocker>

Pointers:
- `<file:line or symbol>` - <why it matters>
- `<wiki/page.md>` - <relevant context>
- `<knowledge/page.md>` - <decision or finding>

Acceptance:
- <observable condition>
- <test/build/check to run>
- <manual smoke test if needed>

## Next Action

<the next smallest useful step for a cold-starting Codex session>

## Pending, Not This Unit

- <deferred gate or follow-up>
