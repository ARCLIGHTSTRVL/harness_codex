---
last_verified_commit: 8237426b6dfcd8810bd3b2f66d6d23021b21c684
last_touched: 2026-09-10
writer: codex
unit_paths: codex/AGENTS.md scripts/native_agents scripts/native-agent-contract.py tests/test_native_routing.py templates skills
---

# NEXT

## Active Unit

Goal: Closed — 0.1.2 source publication and public repository transition verified.
Current state:
- Initial source commit `8237426b6dfcd8810bd3b2f66d6d23021b21c684` is published;
  local `HEAD` and `origin/main` matched at that publication checkpoint.
- The user directed the repository to be renamed `harness_codex` and made public. The
  repository display name changes; compatibility-sensitive package and state names do not.
- The canonical Git tree contains 123 distributed source files plus the repository-only
  `githooks/pre-commit`. The ZIP excludes that hook and adds one synthetic seed instead.
- Staged and tree secret checks passed. The model-name gate passed with exactly the two
  registered historical attribution suppressions.
- Windows reran all 33 tests in 25.143 seconds. The 124-entry publication-validation ZIP
  has SHA-256 `f0f51f26c3d7b3718e02afd667aa09fd5a79010c72113b0a0f69fa83621ef943`.
- The Git-only pre-commit hook is not installed into recipient hook configuration, and
  publication does not establish native hook trust or runtime delivery.
- Knowledge decisions and evidence limits are filed in knowledge/index.md.
Blocker:
- None. No open-source license has been selected by the publication operation.
Pointers:
- docs/PACKAGING.md
- knowledge/journal/2026-09-10-distribution-readiness.md
- `git rev-parse HEAD`
- `git rev-parse origin/main`
- `gh repo view --json visibility`
- START-HERE.md
Acceptance:
- The implementation source commit is reachable at `origin/main`; the repository is
  named `harness_codex` and publicly visible.
- Source gates, the 33-test Windows run and publication-validation ZIP build pass.

## Next Action

No active source work remains. Before starting another unit, compare local `HEAD` with
`origin/main` and use the pinned wiki references to determine whether source contracts
changed. Rebuild the ZIP and its SHA-256 sidecar after documentation closure; the ZIP
contains no Git history or commit pin.

## Pending, Not This Unit

- No open-source license has been selected.
