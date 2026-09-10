---
name: doctor
description: Run the project-level deep health check for NEXT freshness, wiki-lint, kb-lint, fragment consolidation debt, bootstrap template drift, and KR mirror reminders. Use for "doctor", "project health check", "프로젝트 점검", "신선도 점검", or before a milestone.
---

# doctor

Run the deterministic project health checks that are too expensive for casual
orientation.

## Procedure

1. Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json`
   (default CODEX_HOME: `~/.codex`). Use that directory as `<repo>`.

2. From the current project directory, run:

```bash
python <repo>/scripts/doctor.py
```

Use `py` or `python` on Windows if needed.
The repository's sibling `skills/` tools take precedence. Only missing source
tools fall back to `$CODEX_HOME/skills`, or `~/.codex/skills` when unset.

3. Report:
   - NEXT freshness state
   - bootstrap hook/template drift if present
   - wiki-lint result
   - kb-lint result
   - knowledge-fragment consolidation debt
   - context-budget results when the project carries `workflow/context-contracts.yml`
   - external-review pin status for native project configuration
   - native agent catalog state and unresolved completion evidence, including
     pending, unregistered, unverified, mismatch and damaged records
   - KR mirror reminder

## State

Every managed-project run records `<project>/.codex/.last-doctor`. The stamp
records the last run, not the last clean run. ATTENTION still exits 1; ADVISORY
rows remain visible without setting failure. `--help` and invalid arguments do
not stamp. Uncommitted unit work is WIP; committed drift is STALE.
Fragment debt aged 30+ days is advisory. Unmeasurable counts/ages, future
timestamps beyond five minutes, and unacknowledged archive damage require
attention; acknowledged quarantine remains visible without setting failure.

Context contracts use the project's own `scripts/context-cost.py --check` from
the project root. Missing or failed engines and block-tier violations require
attention; warn-tier overages are advisory. No contract means no budget row.

Native agent status reads local records without starting a model request.
A FRESH catalog cannot cancel completion ATTENTION. Missing project pins are
UNSET, not an instruction to select models automatically.

## Boundary

This is project-scoped. For installed harness drift, use `setup-check` or
`dev-setup status`.
